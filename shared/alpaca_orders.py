"""
Direct Alpaca REST order placement.

Replaces the routine-based execution path that was burning the 15-call
daily Anthropic Routines budget. Each monitor now places orders directly
via /v2/orders, mirroring the options-monitor pattern that's been live
since 2026-05-06.

Helpers cover three asset classes:

  place_stock_bracket(symbol, side, qty, entry, sl, tp, strategy)
      Bracket order for stocks/ETFs (Alpaca paper supports brackets).
      side: "buy" (long) or "sell_short" (short)

  place_crypto_order(symbol, side, qty, entry, strategy)
      Simple limit order for BTC/USD, ETH/USD. Alpaca crypto does NOT
      support bracket — TP/SL must be managed separately by exit-monitor.

  place_simple_buy(symbol, qty, limit_price, strategy)
      Simple limit BUY for options (Alpaca paper rejects bracket on
      options — already used by options-monitor).

  get_latest_quote(symbol)
      Single-quote snapshot for SL/TP price computation. Returns
      {bid, ask, mid} or None.

All helpers fail-open: API failure returns None, caller falls through
to email-only / log path. Same fail-open philosophy as risk_guards.
"""

from __future__ import annotations  # v3.11.3: lazy-string annotations so PEP 604 (`X | None`) is parseable on Py 3.9 (CI runs 3.11, but local dev/test runs 3.9).

import os
import re
import urllib.parse
import requests
from datetime import datetime, timezone

ALPACA_BASE_URL = "https://paper-api.alpaca.markets"
ALPACA_DATA_URL = "https://data.alpaca.markets"


# v3.32 (2026-07-04) — canonical ExecutionMode gate. Every broker-mutating
# HTTP call in this module MUST be preceded by _execution_mode_precheck().
# The AST test tests/architecture_vnext/test_alpaca_mutation_sites_gated.py
# scans this file and fails if any requests.post/requests.delete to
# /v2/orders or /v2/positions/* is not dominated by a call to this helper.
#
# Behavior contract:
#   - returns None → caller MAY proceed (mode + preconditions passed)
#   - returns dict → mutation is blocked; caller MUST return the dict as
#     its result (backward-compat shape).
#   - never raises to the caller — uses check_or_block internally, which
#     converts BrokerMutationBlocked to a structured refuse-and-return dict.
def _execution_mode_precheck(
    intent: str,
    intended_notional_usd: float = 0.0,
    client_order_id: str | None = None,
) -> dict | None:
    """v3.32 canonical mutation-guard shim.

    Called at the top of every mutation function BEFORE the broker HTTP
    call. Delegates all authorization logic to shared/execution_mode.py.

    Returns None if the mutation is authorized. Returns a structured
    "blocked" dict if the guard denies — the caller should return that
    dict verbatim (or serialize it into its result contract). The dict
    contains no secrets and only redacted IDs.

    Test hook: environment variable EXECUTION_MODE_GATE_TEST_BYPASS may
    be set to a non-empty value ONLY inside a hermetic test's
    setUpModule; production workflows never set it (verified by CI env
    scan). Fails-closed if the variable is misspelled.
    """
    if os.environ.get("EXECUTION_MODE_GATE_TEST_BYPASS", "").strip():
        # Explicit test-time bypass. NEVER read outside of tests.
        return None
    try:
        try:
            from execution_mode import check_or_block  # type: ignore
        except ImportError:
            from shared.execution_mode import check_or_block  # type: ignore
    except Exception as e:
        # Fail-closed: guard module unavailable → block.
        return {
            "status":         "EXECUTION_MODE_BLOCKED",
            "reason":         f"execution_mode module unavailable ({type(e).__name__}) — fail closed",
            "intent":         intent,
            "guard_decision": "BLOCKED_FAIL_CLOSED",
            "broker_called":  False,
        }
    return check_or_block(
        intent=intent,
        intended_notional_usd=intended_notional_usd,
        idempotency_key=client_order_id,
    )


def _fetch_account() -> dict | None:
    """Best-effort /v2/account for portfolio-risk gate. Returns None on failure."""
    if not _headers()["APCA-API-KEY-ID"]:
        return None
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/v2/account", headers=_headers(), timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _fetch_positions() -> list[dict]:
    if not _headers()["APCA-API-KEY-ID"]:
        return []
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/v2/positions", headers=_headers(), timeout=10)
        if r.status_code == 200:
            return r.json() or []
    except Exception:
        pass
    return []


def _fetch_open_orders() -> list[dict]:
    if not _headers()["APCA-API-KEY-ID"]:
        return []
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/v2/orders",
                         headers=_headers(), params={"status": "open"}, timeout=10)
        if r.status_code == 200:
            return r.json() or []
    except Exception:
        pass
    return []


def _portfolio_risk_gate(symbol: str, side: str, size_usd: float,
                         asset_class: str) -> tuple[bool, list[str], list[str]]:
    """
    Portfolio-level pre-trade gate (spec §D). Returns (ok, failed, warnings).
    Fail-open on missing inputs — same contract as shared/risk_guards.py.
    """
    try:
        try:
            from portfolio_risk import evaluate_portfolio_risk
        except ImportError:
            from shared.portfolio_risk import evaluate_portfolio_risk  # type: ignore
        verdict = evaluate_portfolio_risk(
            proposed_trade = {
                "symbol":      symbol,
                "side":        side,
                "size_usd":    size_usd,
                "asset_class": asset_class,
            },
            account = _fetch_account(),
            positions = _fetch_positions(),
            open_orders = _fetch_open_orders(),
        )
        return verdict["decision"] == "APPROVE", verdict.get("failed", []), verdict.get("warnings", [])
    except Exception as e:  # pragma: no cover
        return True, [], [f"portfolio-risk unavailable ({type(e).__name__}: {e})"]


def _intraday_governor_gate(symbol: str, side: str, size_usd: float,
                            asset_class: str,
                            score: float | None = None) -> tuple[bool, str]:
    """
    IntradayProfitGovernor pre-trade gate. Returns (allow, reason).

    Logic:
      - RED_DAY_AFTER_GREEN / DEFEND_DAY     → BLOCK (deterministic giveback protection)
      - PROFIT_LOCK + score < override       → BLOCK (high-score override is ratchet exit)
      - Account state unavailable            → BLOCK (spec §G fail-closed for new entries)
      - else                                 → ALLOW

    Audit-only: emits a BLOCK_NEW_ENTRIES_INTRADAY event when blocking.
    Fail-open on import error so the governor module being unavailable
    cannot freeze trading (defence in depth: this is layered on top of
    risk_officer + portfolio_risk_gate).
    """
    try:
        try:
            from runtime_config import intraday_protection_enabled
        except ImportError:
            from shared.runtime_config import intraday_protection_enabled  # type: ignore
        if not intraday_protection_enabled():
            return True, "intraday_protection_disabled"
        try:
            from intraday_governor import (
                block_new_entries, emit_audit, get_snapshot,
                EVENT_BLOCK_NEW_ENTRIES_INTRADAY,
            )
        except ImportError:
            from shared.intraday_governor import (   # type: ignore
                block_new_entries, emit_audit, get_snapshot,
                EVENT_BLOCK_NEW_ENTRIES_INTRADAY,
            )
        block, reason = block_new_entries(symbol=symbol, score=score)
        if block:
            try:
                emit_audit(
                    EVENT_BLOCK_NEW_ENTRIES_INTRADAY,
                    get_snapshot(),
                    action="reject_entry",
                    reason=reason,
                    affected_symbols=[symbol],
                )
            except Exception:  # pragma: no cover
                pass
        return (not block), reason
    except Exception as e:  # pragma: no cover
        return True, f"intraday-governor unavailable ({type(e).__name__}: {e})"


def _pdt_gate(symbol: str, side: str, size_usd: float,
              asset_class: str, intent: str = "swing") -> tuple[bool, str]:
    """
    PDT pre-trade gate v3.8 — intent-aware. Returns (allow, reason).

    Default intent="swing" means caller intends to hold ≥1 session. This
    matches every entry-monitor's default behavior (price-monitor opens
    swing positions, options-monitor's contracts hold 7-30 DTE, crypto
    is exempt regardless). Callers doing planned same-day flips MUST
    explicitly pass intent="intraday" so the guard can DEFER in
    RESTRICTED+ states (where the planned close would burn the saved
    DT budget).

    Logic for OPEN actions:
      - LOCKED with BP OK + swing intent  → ALLOW (no DT impact)
      - LOCKED with BP insufficient       → BLOCK (broker would reject)
      - RESTRICTED + intraday intent      → DEFER (planned close = DT)
      - All other combinations            → ALLOW

    Emits non-ALLOW decisions to journal/autonomy/. Fail-open if module
    unavailable — layered above risk_officer which catches absolute BP-
    insufficient case anyway.
    """
    try:
        try:
            from pdt_guard import evaluate_order, record_decision
        except ImportError:
            from shared.pdt_guard import evaluate_order, record_decision  # type: ignore
        action = "OPEN"  # all calls to this gate are entry-side
        verdict = evaluate_order(
            action=action, symbol=symbol, side=side, size_usd=size_usd,
            intent=intent, is_emergency=False,
        )
        decision = verdict.get("decision", "ALLOW")
        reason   = verdict.get("reason", "")
        if decision != "ALLOW":
            record_decision(verdict, action=action, symbol=symbol,
                            extra={"asset_class": asset_class, "size_usd": size_usd,
                                    "intent": intent})
        return (decision == "ALLOW"), reason
    except Exception as e:  # pragma: no cover
        return True, f"pdt-guard unavailable ({type(e).__name__}: {e})"


def _crypto_exposure_policy_gate(
    symbol: str, side: str, size_usd: float, *,
    mode: str = "broker_paper",
) -> tuple[bool, str, str | None]:
    """v3.25.0 (2026-06-09) — hard crypto exposure / laddering / cooldown gate.

    Defense-in-depth wrapper around
    ``shared/crypto_exposure_policy.py::evaluate_crypto_buy``. Runs only
    on the BUY side. Pulls current crypto positions from the existing
    risk_guards helper, pending orders from the existing open-orders
    fetcher, drawdown-guard state from runtime config / portfolio_risk,
    and the per-symbol buy history from runtime_state.json (when present).

    Fail-CLOSED for BUY: if any context call fails, the gate REFUSES the
    buy. This is the v3.25 contract — the SOL/LTC pattern must never
    sneak through because a context fetch errored.

    Returns (ok, reason, decision_token). decision_token is the precise
    enum (e.g. "CRYPTO_BUY_BLOCKED_BY_SYMBOL_EXPOSURE_CAP") for the
    audit / shadow layer.

    No-ops for non-crypto symbols and for the SELL side — returns
    (True, "skip", None).
    """
    s = symbol.upper()
    if not (s.endswith("USD") or s.endswith("/USD")):
        return True, "non-crypto symbol", None
    if side != "buy":
        return True, "sell side — exit policy handles this", None
    try:
        from crypto_exposure_policy import (
            CryptoExposureInputs, evaluate_crypto_buy,
        )
    except ImportError:
        try:
            from shared.crypto_exposure_policy import (
                CryptoExposureInputs, evaluate_crypto_buy,
            )
        except Exception as e:
            return False, f"crypto-exposure-policy import failed ({e})", None

    # Pull live context. Each helper is fail-closed for BUY: any error
    # surfaces as a block reason.
    try:
        try:
            from risk_guards import get_open_positions, get_account_status
        except ImportError:
            from shared.risk_guards import get_open_positions, get_account_status
        positions = get_open_positions() or []
    except Exception as e:
        return False, f"positions fetch failed ({type(e).__name__}: {e})", None
    try:
        account = get_account_status()
        equity_usd = float(account.get("equity") or 0.0) if account else 0.0
    except Exception:
        equity_usd = 0.0
    if equity_usd <= 0:
        return False, "equity unavailable — BUY fail-closed", None

    # Convert positions to {symbol: notional_usd}.
    positions_usd: dict[str, float] = {}
    for pos in positions:
        try:
            sym = (pos.get("symbol") or "").upper()
            if not sym:
                continue
            mv = float(pos.get("market_value")
                        or pos.get("qty") and (
                            float(pos.get("qty", 0))
                            * float(pos.get("current_price", 0))
                        )
                        or 0.0)
            positions_usd[sym] = mv
        except Exception:
            continue

    # Pending orders for this symbol.
    try:
        open_orders = _fetch_open_orders() or []
        pending = sum(
            1 for o in open_orders
            if (o.get("symbol") or "").upper() in (s, s.replace("/", ""))
        )
    except Exception:
        pending = 0

    # Drawdown guard active? Use portfolio_risk profile flag where
    # available. Fail-closed = treat as active if anything unclear (BUY
    # must err on the side of blocking).
    drawdown_active = False
    try:
        from intraday_governor import current_fsm_state
        fsm = current_fsm_state() or {}
        # Any post-PROFIT_LOCK / DEFEND_DAY / RED_DAY_AFTER_GREEN state
        # means new entries should be blocked.
        st = (fsm.get("state") or "").upper()
        if st in ("PROFIT_LOCK", "DEFEND_DAY", "RED_DAY_AFTER_GREEN"):
            drawdown_active = True
    except Exception:
        pass

    # Per-symbol buy history from runtime_state (best-effort).
    buys_today_by_symbol: dict[str, int] = {}
    last_buy_epoch_by_symbol: dict[str, float] = {}
    recent_pnl_by_symbol: dict[str, float] = {}
    try:
        from runtime_state import read_section
        hist = read_section("crypto_buy_history") or {}
        if isinstance(hist, dict):
            buys_today_by_symbol = (hist.get("buys_today_by_symbol")
                                      or {})
            last_buy_epoch_by_symbol = (hist.get("last_buy_epoch_by_symbol")
                                          or {})
            recent_pnl_by_symbol = (hist.get("recent_realized_pnl_by_symbol_usd")
                                      or {})
    except Exception:
        pass

    inputs = CryptoExposureInputs(
        symbol=s,
        proposed_buy_usd=float(size_usd),
        equity_usd=float(equity_usd),
        current_positions_usd=positions_usd,
        pending_orders_by_symbol={s: pending},
        drawdown_guard_active=drawdown_active,
        recent_realized_pnl_by_symbol_usd=recent_pnl_by_symbol,
        buys_today_by_symbol=buys_today_by_symbol,
        last_buy_epoch_by_symbol=last_buy_epoch_by_symbol,
        mode=mode,
    )
    decision = evaluate_crypto_buy(inputs)
    if decision.is_allow or decision.is_shadow_only:
        return True, decision.reason, decision.decision
    return False, decision.reason, decision.decision


def _confidence_gate(confidence_inputs: dict | None,
                     symbol: str = "?") -> tuple[bool, str]:
    """v3.14.0 (2026-06-02) — inline confidence gate (closes CONF-002).

    Used by entry paths that do NOT call risk_officer (e.g. options
    place_simple_buy). For paths that DO call risk_officer, the gate is
    handled there via proposal["confidence_inputs"] — no double-evaluation.

    Returns (allowed, reason). Fail-soft: if confidence module unavailable
    OR confidence_inputs is None, returns (True, "skip"). BLOCK only when
    explicit BLOCK decision returned (low score). ALERT_ONLY warns but
    proceeds.
    """
    if not confidence_inputs:
        return True, "confidence_inputs not provided (legacy caller)"
    try:
        from confidence import compute_confidence  # type: ignore
        report = compute_confidence(**confidence_inputs)
        if report.decision == "BLOCK":
            return False, (f"confidence={report.total:.3f} < threshold "
                           f"(weakest={min(report.components, key=report.components.get)})")
        if report.decision == "ALERT_ONLY":
            print(f"  confidence ALERT_ONLY {symbol}: total={report.total:.3f} — proceeding")
        return True, f"confidence_ok={report.total:.3f}"
    except Exception as e:
        return True, f"confidence-gate unavailable ({type(e).__name__}: {e})"


def _emit_entry_audit_event(*, proposal: dict, result: str,
                            result_reason: str = "",
                            order: dict | None = None,
                            risk_verdict: dict | None = None) -> None:
    """v3.17.0 (2026-06-04, Task 3) — Emit one entry audit JSONL event.

    Thin wrapper around shared._entry_audit.emit_entry_audit so the call
    sites in place_stock_bracket / place_crypto_order / place_simple_buy
    stay short and uniform. NEVER raises — audit emit failure cannot
    block the entry decision (the decision is already made by the time
    we call this). Audit emit propagates the existing
    `proposal["_confidence_report"]` if risk_officer attached it.
    """
    try:
        try:
            from _entry_audit import emit_entry_audit  # type: ignore
        except ImportError:
            from shared._entry_audit import emit_entry_audit  # type: ignore
        emit_entry_audit(
            proposal=proposal,
            result=result,
            result_reason=result_reason,
            order=order,
            risk_verdict=risk_verdict,
            actor="alpaca_orders",
        )
    except Exception as e:  # pragma: no cover — defensive fallback
        print(f"  ⚠️  _emit_entry_audit_event failed (non-fatal): "
              f"{type(e).__name__}: {e}")


# ─── v3.22 — entry gate stack (confidence MANDATORY + canary preflight) ───────

# Stable string verdicts surfaced to callers + audit pipeline. Never change
# the literal values; downstream tests + dashboards key on them.
V322_REJECT_NO_CONFIDENCE_INPUTS = "REJECTED_NO_CONFIDENCE_INPUTS"
V322_REJECT_CANARY_PREFLIGHT     = "REJECTED_CANARY_PREFLIGHT"
V322_REJECT_CANARY_DEFERRED      = (
    "REJECTED_CANARY_ORDER_PLACEMENT_DEFERRED")
V322_REJECT_CANARY_UNAVAILABLE   = "REJECTED_CANARY_PREFLIGHT_UNAVAILABLE"

# Verdicts the preflight can return that mean "preflight green / OK"; in
# v3.22 BOTH still produce no broker call (DEFERRED is the hard ceiling).
_V322_PREFLIGHT_OK_VERDICTS = frozenset({
    "CANARY_PREFLIGHT_DRY_RUN_OK",
    "CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED",
})


def _read_latest_unlock_status_safe() -> str | None:
    """Read `unlock_status` from learning-loop/broker_paper_canary/
    unlock_readiness_latest.json. Fail-soft: any error → None.

    v3.22 caller (`_v322_entry_gate_stack`) feeds this to the canary
    preflight so the preflight can refuse with UNLOCK_NOT_READY when
    the readiness file says we are still STAGE_0_SHADOW_ONLY (the
    default v3.30 state).
    """
    try:
        # Module-local import to keep the top-level import surface lean
        # and to avoid eager pathlib resolution at import time.
        from pathlib import Path
        import json as _json
        repo_root = Path(__file__).resolve().parent.parent
        p = (repo_root
             / "learning-loop"
             / "broker_paper_canary"
             / "unlock_readiness_latest.json")
        if not p.exists():
            return None
        d = _json.loads(p.read_text(encoding="utf-8"))
        return d.get("unlock_status")
    except Exception:
        return None


def _v322_entry_gate_stack(
    proposal: dict,
    *,
    confidence_inputs: dict | None,
    observe_only: bool = False,
    entry_capable: bool = True,
) -> tuple[bool, str, str]:
    """v3.22 entry gate stack — MANDATORY for every entry-capable path.

    Two gates, in order:
      (1) Confidence-inputs MANDATORY for entry-capable callers. Empty
          / missing → REJECT with reason ``REJECTED_NO_CONFIDENCE_INPUTS``
          and audit event ``REJECT_ENTRY_NO_CONFIDENCE_INPUTS``.
      (2) Canary preflight is consulted (fail-CLOSED). Refusal verdicts
          → REJECT. Even the "all-green" verdict
          ``CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED``
          BLOCKS at the architectural level in v3.22 — we are wiring the
          gate so that the v3.31+ executor cannot be added without the
          preflight already in place. ``CANARY_PREFLIGHT_DRY_RUN_OK``
          also returns BLOCK because v3.22 does not execute orders.

    Back-compat: callers that flag ``observe_only=True`` OR
    ``entry_capable=False`` (e.g. shadow-mode pipelines, legacy paths
    that explicitly opt out) get gate-1 relaxed (no confidence required)
    but gate-2 still applies — the architectural deferral holds.

    Returns ``(ok, verdict, reason)``:
      - ``ok=True`` → the caller MAY proceed (only for observe-only).
      - ``ok=False`` → the caller MUST return None and emit audit.

    NEVER raises. Fail-CLOSED on every internal exception.
    """
    symbol = str(proposal.get("symbol", "?"))

    # ── Back-compat: observe_only / entry_capable=False relax gate 1 ─────
    # The architectural deferral still runs (gate 2) — v3.22 keeps the
    # "no broker call" invariant even for observe_only callers because
    # order placement is not implemented yet in any path.
    _gate1_skip = bool(observe_only or not entry_capable)
    if _gate1_skip and not confidence_inputs:
        print(f"  v3.22 gate-stack {symbol}: confidence_inputs missing "
              f"but observe_only/entry_capable=False — soft-skipping "
              f"gate-1, still applying gate-2")

    # ── Gate 1: confidence_inputs MANDATORY (unless observe_only) ────────
    if not _gate1_skip and (not confidence_inputs or not isinstance(confidence_inputs, dict)):
        reason = (
            f"v3.22 gate-stack BLOCK {symbol}: entry path requires "
            f"confidence_inputs (empty/missing); refusing entry")
        print(f"  {reason}")
        _emit_entry_audit_event(
            proposal=proposal,
            result="rejected",
            result_reason="REJECT_ENTRY_NO_CONFIDENCE_INPUTS — "
                          "confidence_inputs missing on entry path",
        )
        return False, V322_REJECT_NO_CONFIDENCE_INPUTS, reason

    # ── Gate 2: canary preflight (fail-CLOSED) ───────────────────────────
    try:
        try:
            from broker_paper_canary_preflight import run_preflight  # type: ignore  # noqa: E402
        except ImportError:
            from shared.broker_paper_canary_preflight import run_preflight  # type: ignore  # noqa: E402
    except Exception as e:
        reason = (
            f"v3.22 gate-stack BLOCK {symbol}: canary preflight module "
            f"unavailable ({type(e).__name__}: {e}); refusing entry "
            f"(fail-CLOSED)")
        print(f"  {reason}")
        _emit_entry_audit_event(
            proposal=proposal,
            result="rejected",
            result_reason="REJECT_ENTRY_CANARY_UNAVAILABLE — "
                          f"{type(e).__name__}: {e}",
        )
        return False, V322_REJECT_CANARY_UNAVAILABLE, reason

    unlock_status = _read_latest_unlock_status_safe()
    # In v3.22, dry-run mode is the SAFE default. Operator must
    # explicitly set CANARY_DRY_RUN=false to even attempt the
    # non-dry-run preflight, and even then the verdict caps at
    # DEFERRED in v3.30+ → still BLOCK here.
    dry_run_only = (os.environ.get(
        "CANARY_DRY_RUN", "true").strip().lower() != "false")

    try:
        verdict_obj = run_preflight(
            unlock_status=unlock_status,
            dry_run_only=dry_run_only,
        )
    except Exception as e:
        reason = (
            f"v3.22 gate-stack BLOCK {symbol}: canary preflight raised "
            f"({type(e).__name__}: {e}); refusing entry (fail-CLOSED)")
        print(f"  {reason}")
        _emit_entry_audit_event(
            proposal=proposal,
            result="rejected",
            result_reason="REJECT_ENTRY_CANARY_RAISED — "
                          f"{type(e).__name__}: {e}",
        )
        return False, V322_REJECT_CANARY_UNAVAILABLE, reason

    pf_verdict = getattr(verdict_obj, "verdict", None) or "UNKNOWN"

    if pf_verdict not in _V322_PREFLIGHT_OK_VERDICTS:
        reason = (
            f"v3.22 gate-stack BLOCK {symbol}: canary preflight refused "
            f"({pf_verdict}); refusing entry")
        print(f"  {reason}")
        _emit_entry_audit_event(
            proposal=proposal,
            result="rejected",
            result_reason=f"REJECT_ENTRY_CANARY_PREFLIGHT — {pf_verdict}",
        )
        return False, V322_REJECT_CANARY_PREFLIGHT, reason

    # v3.22 hard rule: even all-green preflight does NOT advance to a
    # broker call. The current sprint only wires the gate; order
    # placement remains blocked architecturally. v3.31+ will add the
    # actual placement under an audited PR.
    reason = (
        f"v3.22 gate-stack BLOCK {symbol}: preflight ok ({pf_verdict}) "
        f"BUT v3.22 does not advance entry paths to broker calls "
        f"(architectural deferral)")
    print(f"  {reason}")
    _emit_entry_audit_event(
        proposal=proposal,
        result="rejected",
        result_reason=f"REJECT_ENTRY_CANARY_ORDER_PLACEMENT_DEFERRED — "
                      f"{pf_verdict}",
    )
    return False, V322_REJECT_CANARY_DEFERRED, reason


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID":     os.environ.get("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.environ.get("ALPACA_SECRET_KEY", ""),
    }


def _client_order_id(strategy: str, symbol: str) -> str:
    """Per-strategy client_order_id so exit-monitor + analyzer can attribute origin.

    v3.8.5 (2026-05-16): defensive validation. Hard-rejects truly broken
    inputs (None, empty, UUID-shaped). Allows "auto" (legacy default)
    with a warning print — analyzer parses "auto-SYM-ts" as strategy
    "auto" which is at least not UUID pollution.

    LLM-flagged 2026-05-15: 'Unknown strategy tag — 10.8h order, no
    attribution' — that was an order placed with empty strategy. The
    None/empty rejection catches this at source.
    """
    if not strategy or not isinstance(strategy, str):
        raise ValueError(
            f"_client_order_id requires non-empty strategy name; got {strategy!r}. "
            f"Every order MUST carry attribution for analyzer to compute "
            f"per-strategy P&L."
        )
    strategy_clean = strategy.strip().lower()
    if not strategy_clean:
        raise ValueError(f"strategy is empty after strip; got {strategy!r}")
    # Reject if strategy itself looks UUID-ish (would pollute analyzer).
    if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}", strategy_clean):
        raise ValueError(
            f"strategy={strategy!r} looks like a UUID prefix; analyzer would "
            f"treat the resulting client_order_id as 'unknown'. Use a real strategy name."
        )
    # 'auto' is the historical fallback default — log a soft warning so we
    # can spot call sites that should be passing a real name. Not fatal.
    if strategy_clean == "auto":
        print(f"  ⚠️  _client_order_id: strategy='auto' for {symbol} — caller "
              f"should pass an explicit strategy name (e.g. 'momentum-long', "
              f"'allocator-rebalance', 'op-correction')")
    ts = datetime.now(timezone.utc).strftime("%H%M%S%f")[:-3]
    safe_sym = symbol.replace("/", "").replace(" ", "")
    return f"{strategy_clean}-{safe_sym}-{ts}"


# ─── Quote / spot price ───────────────────────────────────────────────────────

def get_latest_quote(symbol: str) -> dict | None:
    """
    Returns {bid, ask, mid} for `symbol`, or None on failure.

    Used by entry monitors that need a current spot price to compute
    SL/TP from percentage thresholds.
    """
    if not _headers()["APCA-API-KEY-ID"]:
        return None
    try:
        r = requests.get(
            f"{ALPACA_DATA_URL}/v2/stocks/{urllib.parse.quote(symbol, safe='')}/quotes/latest",
            headers=_headers(),
            params={"feed": "iex"},
            timeout=10,
        )
        r.raise_for_status()
        q = r.json().get("quote", {})
        bid = float(q.get("bp", 0))
        ask = float(q.get("ap", 0))
        if bid <= 0 or ask <= 0:
            return None
        return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2.0}
    except Exception as e:
        print(f"  quote {symbol} error: {e}")
        return None


def get_latest_crypto_quote(symbol: str) -> dict | None:
    """Returns {bid, ask, mid} for crypto symbol like 'BTC/USD'."""
    if not _headers()["APCA-API-KEY-ID"]:
        return None
    try:
        r = requests.get(
            f"{ALPACA_DATA_URL}/v1beta3/crypto/us/latest/quotes",
            headers=_headers(),
            params={"symbols": symbol},
            timeout=10,
        )
        r.raise_for_status()
        d = r.json().get("quotes", {}).get(symbol, {})
        bid = float(d.get("bp", 0))
        ask = float(d.get("ap", 0))
        if bid <= 0 or ask <= 0:
            return None
        return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2.0}
    except Exception as e:
        print(f"  crypto quote {symbol} error: {e}")
        return None


# ─── Order placement ──────────────────────────────────────────────────────────

def place_stock_bracket(symbol: str, side: str, qty: int,
                        entry_price: float, stop_loss: float,
                        take_profit: float,
                        strategy: str = "auto",
                        confidence_inputs: dict | None = None,
                        observe_only: bool = False,
                        entry_capable: bool = True) -> dict | None:
    """
    Place a bracket order for stocks/ETFs.

    side:        "buy" (long) or "sell_short" (short)
    qty:         integer shares (>= 1)
    entry_price: limit price for entry leg
    stop_loss:   absolute price for SL leg
    take_profit: absolute price for TP leg
    strategy:    used in client_order_id prefix

    v3.22 (2026-06-15) entry-capable callers MUST pass
    ``confidence_inputs``. Missing → REJECTED_NO_CONFIDENCE_INPUTS. Canary
    preflight is consulted; even all-green preflight still BLOCKs in v3.22
    because order placement remains architecturally deferred.

    Returns the Alpaca order JSON on success, None on failure (incl.
    risk-officer REJECT — see shared.risk_officer.evaluate_trade).
    """
    if qty < 1 or entry_price <= 0 or stop_loss <= 0 or take_profit <= 0:
        print(f"  bracket reject: qty={qty} entry={entry_price} sl={stop_loss} tp={take_profit}")
        return None
    if side not in ("buy", "sell_short"):
        print(f"  bracket reject: bad side '{side}'")
        return None

    # v3.22 (2026-06-15) — entry gate stack: confidence MANDATORY +
    # canary preflight. Runs BEFORE per-instrument window so that a
    # legacy / mis-wired caller can never reach the broker. The stack
    # already emits audit JSONL on every BLOCK path.
    _v322_proposal = {
        "symbol":      symbol,
        "action":      "BUY" if side == "buy" else "SELL_SHORT",
        "size_usd":    qty * entry_price,
        "entry_price": entry_price,
        "stop_loss":   stop_loss,
        "take_profit": take_profit,
        "strategy":    strategy,
    }
    if confidence_inputs:
        _v322_proposal["confidence_inputs"] = confidence_inputs
    _v322_ok, _v322_verdict, _v322_reason = _v322_entry_gate_stack(
        _v322_proposal,
        confidence_inputs=confidence_inputs,
        observe_only=observe_only,
        entry_capable=entry_capable,
    )
    if not _v322_ok:
        return None

    # Per-instrument trading window gate (final guard right before POST).
    # Most callers also gate upstream in execute_stock_signal — this is the
    # belt-and-braces check that catches direct callers (allocator, etc.).
    try:
        from instrument_windows import can_trade_now
    except ImportError:
        from shared.instrument_windows import can_trade_now
    ok, reason = can_trade_now(symbol, asset_class="us_equity")
    if not ok:
        print(f"  bracket reject {symbol}: trade-window — {reason}")
        return None

    # Portfolio-level risk gate (spec §D). Runs BEFORE risk-officer so a
    # symbol+bucket+gross check happens even if USE_RISK_OFFICER=false.
    pr_ok, pr_failed, pr_warns = _portfolio_risk_gate(
        symbol=symbol, side=side, size_usd=qty * entry_price, asset_class="us_equity",
    )
    if not pr_ok:
        print(f"  PORTFOLIO-RISK REJECT {symbol}: {'; '.join(pr_failed)}")
        return None
    for w in pr_warns:
        print(f"  portfolio-risk warn: {w}")

    # IntradayProfitGovernor gate (spec §11 entry-monitor gating). Blocks
    # new entries during DEFEND_DAY / RED_DAY_AFTER_GREEN and below-score
    # entries during PROFIT_LOCK. Audit event written if blocked.
    ig_score = None  # caller may pass score via kwargs (future); see place_simple_buy
    ig_ok, ig_reason = _intraday_governor_gate(
        symbol=symbol, side=side, size_usd=qty * entry_price,
        asset_class="us_equity", score=ig_score,
    )
    if not ig_ok:
        print(f"  INTRADAY-GOVERNOR BLOCK {symbol}: {ig_reason}")
        return None

    # PDT gate — preventive layer above risk_officer's BP check. Blocks new
    # entries when account is in LOCKED state (BP < required) so monitors
    # don't keep spamming Alpaca with 403-bound orders.
    pdt_ok, pdt_reason = _pdt_gate(
        symbol=symbol, side=side, size_usd=qty * entry_price,
        asset_class="us_equity",
    )
    if not pdt_ok:
        print(f"  PDT-GUARD BLOCK {symbol}: {pdt_reason}")
        return None

    # Risk-officer gate (opt-out via USE_RISK_OFFICER=false). Hard violations
    # block the trade; soft warnings are logged but don't reject.
    #
    # v3.17.0 (2026-06-04, Task 2) — FAIL-CLOSED for new entries. If the
    # risk_officer module is unavailable OR evaluate_trade raises, REFUSE
    # the entry. Critical gates failing must not silently let an order
    # through. This applies ONLY to NEW ENTRIES; emergency closes /
    # safe_close paths still operate (they bypass risk_officer entirely).
    _proposal = {
        "symbol":      symbol,
        "action":      "BUY" if side == "buy" else "SELL_SHORT",
        "size_usd":    qty * entry_price,
        "entry_price": entry_price,
        "stop_loss":   stop_loss,
        "take_profit": take_profit,
        "strategy":    strategy,
    }
    # v3.14.0 (2026-06-02) — pass confidence_inputs through (closes CONF-002).
    if confidence_inputs:
        _proposal["confidence_inputs"] = confidence_inputs
    try:
        try:
            from risk_officer import evaluate_trade  # type: ignore  # noqa: E402
        except ImportError:
            from shared.risk_officer import evaluate_trade  # type: ignore  # noqa: E402
    except Exception as e:
        reason = (
            f"risk-officer module unavailable ({type(e).__name__}: {e}); "
            f"refusing entry (fail-closed)"
        )
        print(f"  RISK-OFFICER UNAVAILABLE {symbol}: {reason}")
        _emit_entry_audit_event(
            proposal=_proposal, result="rejected", result_reason=reason,
        )
        return None
    try:
        verdict = evaluate_trade(_proposal)
    except Exception as e:
        reason = (
            f"risk-officer exception ({type(e).__name__}: {e}); "
            f"refusing entry (fail-closed)"
        )
        print(f"  RISK-OFFICER EXCEPTION {symbol}: {reason}")
        _emit_entry_audit_event(
            proposal=_proposal, result="rejected", result_reason=reason,
        )
        return None
    if verdict.get("decision") == "REJECT":
        print(f"  RISK-OFFICER REJECT {symbol}: {verdict['rationale']}")
        for f in verdict.get("checks_failed", []):
            print(f"    - {f}")
        _emit_entry_audit_event(
            proposal=_proposal, result="rejected",
            result_reason=f"risk-officer REJECT: {verdict.get('rationale','')}",
            risk_verdict=verdict,
        )
        return None
    if verdict.get("warnings"):
        print(f"  risk-officer warnings ({symbol}):")
        for w in verdict["warnings"]:
            print(f"    - {w}")

    # v3.9.6 (2026-05-22 — post-incident fix). TIF was "day" which caused
    # bracket OCO children (SL+TP) to EXPIRE at market close, leaving
    # positions naked overnight. autonomous-remediation then detected
    # "no exit order" and force-closed at next market open — see
    # docs/INCIDENT-2026-05-22-positions-closed.md.
    # GTC keeps both bracket children alive across sessions. Alpaca
    # paper supports GTC bracket; if rejected, env REMEDIATION_DISABLE_RECREATE
    # is the operator safety net.
    payload = {
        "symbol":         symbol,
        "qty":            str(int(qty)),
        "side":           side,
        "type":           "limit",
        "limit_price":    str(round(entry_price, 2)),
        "time_in_force":  "gtc",
        "order_class":    "bracket",
        "take_profit":    {"limit_price": str(round(take_profit, 2))},
        "stop_loss":      {"stop_price":  str(round(stop_loss, 2))},
        "client_order_id": _client_order_id(strategy, symbol),
    }
    # v3.32 — canonical ExecutionMode gate. Blocks BEFORE the broker HTTP
    # call unless mode=PAPER_CANARY and all 12 preconditions pass.
    _gate = _execution_mode_precheck(
        intent="place_stock_bracket",
        intended_notional_usd=float(size_usd),
        client_order_id=payload["client_order_id"],
    )
    if _gate is not None:
        _emit_entry_audit_event(
            proposal=_proposal, result="failed",
            result_reason=f"execution_mode blocked: {_gate.get('reason','')[:180]}",
            risk_verdict=verdict,
        )
        return None
    try:
        r = requests.post(f"{ALPACA_BASE_URL}/v2/orders",
                          headers=_headers(), json=payload, timeout=15)
        if r.status_code in (200, 201):
            order = r.json()
            _emit_entry_audit_event(
                proposal=_proposal, result="placed",
                result_reason="bracket order placed",
                order=order, risk_verdict=verdict,
            )
            return order
        print(f"  Alpaca bracket error {r.status_code}: {r.text[:200]}")
        _emit_entry_audit_event(
            proposal=_proposal, result="failed",
            result_reason=f"Alpaca {r.status_code}: {r.text[:200]}",
            risk_verdict=verdict,
        )
        return None
    except Exception as e:
        print(f"  Alpaca bracket exception: {e}")
        _emit_entry_audit_event(
            proposal=_proposal, result="failed",
            result_reason=f"broker exception: {type(e).__name__}: {e}",
            risk_verdict=verdict,
        )
        return None


def place_crypto_order(symbol: str, side: str, qty: float,
                       limit_price: float,
                       strategy: str = "auto",
                       confidence_inputs: dict | None = None,
                       observe_only: bool = False,
                       entry_capable: bool = True) -> dict | None:
    """
    Place a simple limit order for crypto (Alpaca crypto does NOT support
    bracket / OCO).

    SL/TP must be managed separately — exit-monitor's crypto thresholds
    (CRYPTO_DECAY_HOURS=48 in v2.0, plus per-position trailing) handle
    exit timing.

    v3.22 (2026-06-15) entry-capable callers MUST pass
    ``confidence_inputs``. Same architectural deferral as
    ``place_stock_bracket``.
    """
    if qty <= 0 or limit_price <= 0:
        return None
    if side not in ("buy", "sell"):
        return None

    # v3.22 (2026-06-15) — entry gate stack.
    _v322_proposal = {
        "symbol":      symbol,
        "action":      "BUY" if side == "buy" else "SELL_SHORT",
        "size_usd":    qty * limit_price,
        "entry_price": limit_price,
        "strategy":    strategy,
    }
    if confidence_inputs:
        _v322_proposal["confidence_inputs"] = confidence_inputs
    _v322_ok, _v322_verdict, _v322_reason = _v322_entry_gate_stack(
        _v322_proposal,
        confidence_inputs=confidence_inputs,
        observe_only=observe_only,
        entry_capable=entry_capable,
    )
    if not _v322_ok:
        return None

    # Per-instrument trading window gate.
    try:
        from instrument_windows import can_trade_now
    except ImportError:
        from shared.instrument_windows import can_trade_now
    ok, reason = can_trade_now(symbol, asset_class="crypto")
    if not ok:
        print(f"  crypto reject {symbol}: trade-window — {reason}")
        return None

    # Portfolio-level risk gate (spec §D).
    pr_ok, pr_failed, pr_warns = _portfolio_risk_gate(
        symbol=symbol, side=side, size_usd=qty * limit_price, asset_class="crypto",
    )
    if not pr_ok:
        print(f"  PORTFOLIO-RISK REJECT {symbol}: {'; '.join(pr_failed)}")
        return None
    for w in pr_warns:
        print(f"  portfolio-risk warn: {w}")

    # IntradayProfitGovernor gate — same contract as stocks. Crypto trades
    # 24/7 so this is especially important after a red close on Friday
    # ratcheted us into DEFEND_DAY: weekend crypto entries would otherwise
    # silently rebuild exposure we just spent the session reducing.
    ig_ok, ig_reason = _intraday_governor_gate(
        symbol=symbol, side=side, size_usd=qty * limit_price,
        asset_class="crypto", score=None,
    )
    if not ig_ok:
        print(f"  INTRADAY-GOVERNOR BLOCK {symbol}: {ig_reason}")
        return None

    # PDT gate (crypto exempt from PDT rule, but BP-locked state still
    # blocks here when buying_power < size_usd). Allows clean refusal
    # before broker 403s.
    pdt_ok, pdt_reason = _pdt_gate(
        symbol=symbol, side=side, size_usd=qty * limit_price,
        asset_class="crypto",
    )
    if not pdt_ok:
        print(f"  PDT-GUARD BLOCK {symbol}: {pdt_reason}")
        return None

    # v3.25.0 (2026-06-09) — hard crypto exposure / laddering / cooldown
    # policy. Defense-in-depth on top of portfolio_risk_gate. Specifically
    # designed to block the SOL/LTC pattern (per-cron $2,500 buys that
    # accumulated to ~$30k cost basis per symbol). Fail-CLOSED for buys.
    cep_ok, cep_reason, cep_decision = _crypto_exposure_policy_gate(
        symbol=symbol, side=side, size_usd=qty * limit_price,
        mode="broker_paper",
    )
    if not cep_ok:
        print(f"  CRYPTO-EXPOSURE-POLICY BLOCK {symbol} "
              f"[{cep_decision}]: {cep_reason}")
        return None

    # Risk-officer gate. Crypto orders don't carry SL/TP at the broker
    # (Alpaca crypto = simple limit only); we pass the strategy-level
    # values so the officer can validate R:R and per-trade size.
    #
    # v3.17.0 (2026-06-04, Task 2) — FAIL-CLOSED for new entries. If the
    # risk_officer module is unavailable OR evaluate_trade raises, REFUSE
    # the entry. Critical gates failing must not silently let an order
    # through.
    _proposal = {
        "symbol":      symbol,
        "action":      "BUY" if side == "buy" else "SELL_SHORT",
        "size_usd":    qty * limit_price,
        "entry_price": limit_price,
        "stop_loss":   limit_price * 0.93 if side == "buy" else limit_price * 1.07,
        "take_profit": limit_price * 1.20 if side == "buy" else limit_price * 0.80,
        "strategy":    strategy,
    }
    # v3.14.0 (2026-06-02) — pass confidence_inputs through (closes CONF-002).
    if confidence_inputs:
        _proposal["confidence_inputs"] = confidence_inputs
    try:
        try:
            from risk_officer import evaluate_trade  # type: ignore  # noqa: E402
        except ImportError:
            from shared.risk_officer import evaluate_trade  # type: ignore  # noqa: E402
    except Exception as e:
        reason = (
            f"risk-officer module unavailable ({type(e).__name__}: {e}); "
            f"refusing entry (fail-closed)"
        )
        print(f"  RISK-OFFICER UNAVAILABLE {symbol}: {reason}")
        _emit_entry_audit_event(
            proposal=_proposal, result="rejected", result_reason=reason,
        )
        return None
    try:
        verdict = evaluate_trade(_proposal)
    except Exception as e:
        reason = (
            f"risk-officer exception ({type(e).__name__}: {e}); "
            f"refusing entry (fail-closed)"
        )
        print(f"  RISK-OFFICER EXCEPTION {symbol}: {reason}")
        _emit_entry_audit_event(
            proposal=_proposal, result="rejected", result_reason=reason,
        )
        return None
    if verdict.get("decision") == "REJECT":
        print(f"  RISK-OFFICER REJECT {symbol}: {verdict['rationale']}")
        for f in verdict.get("checks_failed", []):
            print(f"    - {f}")
        _emit_entry_audit_event(
            proposal=_proposal, result="rejected",
            result_reason=f"risk-officer REJECT: {verdict.get('rationale','')}",
            risk_verdict=verdict,
        )
        return None
    if verdict.get("warnings"):
        print(f"  risk-officer warnings ({symbol}):")
        for w in verdict["warnings"]:
            print(f"    - {w}")

    payload = {
        "symbol":         symbol,
        "qty":            str(qty),
        "side":           side,
        "type":           "limit",
        "limit_price":    str(round(limit_price, 2)),
        "time_in_force":  "gtc",   # crypto requires gtc
        "client_order_id": _client_order_id(strategy, symbol),
    }
    # v3.32 — canonical ExecutionMode gate for crypto order path.
    _gate = _execution_mode_precheck(
        intent="place_crypto_order",
        intended_notional_usd=float(size_usd),
        client_order_id=payload["client_order_id"],
    )
    if _gate is not None:
        _emit_entry_audit_event(
            proposal=_proposal, result="failed",
            result_reason=f"execution_mode blocked: {_gate.get('reason','')[:180]}",
            risk_verdict=verdict,
        )
        return None
    try:
        r = requests.post(f"{ALPACA_BASE_URL}/v2/orders",
                          headers=_headers(), json=payload, timeout=15)
        if r.status_code in (200, 201):
            order = r.json()
            _emit_entry_audit_event(
                proposal=_proposal, result="placed",
                result_reason="crypto order placed",
                order=order, risk_verdict=verdict,
            )
            return order
        print(f"  Alpaca crypto order error {r.status_code}: {r.text[:200]}")
        _emit_entry_audit_event(
            proposal=_proposal, result="failed",
            result_reason=f"Alpaca {r.status_code}: {r.text[:200]}",
            risk_verdict=verdict,
        )
        return None
    except Exception as e:
        print(f"  Alpaca crypto order exception: {e}")
        _emit_entry_audit_event(
            proposal=_proposal, result="failed",
            result_reason=f"broker exception: {type(e).__name__}: {e}",
            risk_verdict=verdict,
        )
        return None


def place_simple_buy(symbol: str, qty: int, limit_price: float,
                     strategy: str = "auto",
                     score: float | None = None,
                     confidence_inputs: dict | None = None,
                     observe_only: bool = False,
                     entry_capable: bool = True) -> dict | None:
    """
    Simple limit BUY for instruments that don't support brackets.
    Used by options-monitor (Alpaca paper rejects bracket on options).

    `score` is the entry signal's composite score [0..1]. When the intraday
    governor is in PROFIT_LOCK, scores below profit_lock_min_score_override
    (default 0.65) are blocked — only very high-conviction setups punch
    through. Pass score=None to be treated as "low conviction" (blocked).

    v3.22 (2026-06-15) entry-capable callers MUST pass
    ``confidence_inputs``. Same architectural deferral as the other
    entry paths.
    """
    if qty < 1 or limit_price <= 0:
        return None

    # v3.22 (2026-06-15) — entry gate stack.
    _v322_proposal = {
        "symbol":      symbol,
        "action":      "BUY_TO_OPEN",
        "size_usd":    qty * limit_price,
        "entry_price": limit_price,
        "strategy":    strategy,
    }
    if confidence_inputs:
        _v322_proposal["confidence_inputs"] = confidence_inputs
    _v322_ok, _v322_verdict, _v322_reason = _v322_entry_gate_stack(
        _v322_proposal,
        confidence_inputs=confidence_inputs,
        observe_only=observe_only,
        entry_capable=entry_capable,
    )
    if not _v322_ok:
        return None

    # Per-instrument trading window gate (options trade only during regular
    # equity session).
    try:
        from instrument_windows import can_trade_now
    except ImportError:
        from shared.instrument_windows import can_trade_now
    ok, reason = can_trade_now(symbol, asset_class="us_option")
    if not ok:
        print(f"  simple_buy reject {symbol}: trade-window — {reason}")
        return None

    # IntradayProfitGovernor gate. Options are reduced FIRST in PROFIT_LOCK
    # cascade so new options entries during a giveback are particularly
    # contraindicated (they bleed fast and worsen the very state we're
    # protecting against).
    ig_ok, ig_reason = _intraday_governor_gate(
        symbol=symbol, side="buy", size_usd=qty * limit_price,
        asset_class="us_option", score=score,
    )
    if not ig_ok:
        print(f"  INTRADAY-GOVERNOR BLOCK {symbol} (options): {ig_reason}")
        return None

    # PDT gate — options ARE subject to PDT and burn day-trade count fast.
    # When account is RESTRICTED, opening options is allowed but the
    # exit-monitor will defer same-day closes via its own pdt_guard check.
    pdt_ok, pdt_reason = _pdt_gate(
        symbol=symbol, side="buy", size_usd=qty * limit_price,
        asset_class="us_option",
    )
    if not pdt_ok:
        print(f"  PDT-GUARD BLOCK {symbol} (options): {pdt_reason}")
        return None

    # v3.14.0 (2026-06-02) — confidence gate (closes CONF-002).
    # Options path doesn't call risk_officer; gate inline.
    #
    # v3.17.0 (2026-06-04, Task 2) — FAIL-CLOSED for options entries.
    # Options entries bypass risk_officer by design (Alpaca paper
    # AUTO_EXECUTE rule). The confidence gate is the primary critical
    # check. If the confidence module raises, REFUSE the entry.
    # _confidence_gate's existing contract already returns (True, "skip")
    # when confidence_inputs is None (legacy caller) which we keep —
    # only EXCEPTIONS inside compute_confidence become fail-closed.
    _proposal_options = {
        "symbol":      symbol,
        "action":      "BUY_TO_OPEN",
        "size_usd":    qty * limit_price,
        "entry_price": limit_price,
        "strategy":    strategy,
    }
    try:
        conf_ok, conf_reason = _confidence_gate(confidence_inputs, symbol=symbol)
    except Exception as e:
        # _confidence_gate is itself fail-soft internally, but guard
        # against any escape just in case.
        reason = (
            f"confidence-gate exception ({type(e).__name__}: {e}); "
            f"refusing options entry (fail-closed)"
        )
        print(f"  CONFIDENCE EXCEPTION {symbol} (options): {reason}")
        _emit_entry_audit_event(
            proposal=_proposal_options, result="rejected", result_reason=reason,
        )
        return None
    if not conf_ok:
        print(f"  CONFIDENCE BLOCK {symbol} (options): {conf_reason}")
        _emit_entry_audit_event(
            proposal=_proposal_options, result="rejected",
            result_reason=f"confidence-gate BLOCK: {conf_reason}",
        )
        return None
    if confidence_inputs:
        print(f"  confidence-gate {symbol}: {conf_reason}")

    payload = {
        "symbol":         symbol,
        "qty":            str(int(qty)),
        "side":           "buy",
        "type":           "limit",
        "limit_price":    str(round(limit_price, 2)),
        "time_in_force":  "day",
        "client_order_id": _client_order_id(strategy, symbol),
    }
    # v3.32 — canonical ExecutionMode gate for options simple-buy path.
    _gate = _execution_mode_precheck(
        intent="place_simple_buy",
        intended_notional_usd=float(qty) * float(limit_price) * 100.0,
        client_order_id=payload["client_order_id"],
    )
    if _gate is not None:
        _emit_entry_audit_event(
            proposal=_proposal_options, result="failed",
            result_reason=f"execution_mode blocked: {_gate.get('reason','')[:180]}",
        )
        return None
    try:
        r = requests.post(f"{ALPACA_BASE_URL}/v2/orders",
                          headers=_headers(), json=payload, timeout=15)
        if r.status_code in (200, 201):
            order = r.json()
            _emit_entry_audit_event(
                proposal=_proposal_options, result="placed",
                result_reason="options buy_to_open placed",
                order=order,
            )
            return order
        print(f"  Alpaca simple buy error {r.status_code}: {r.text[:200]}")
        _emit_entry_audit_event(
            proposal=_proposal_options, result="failed",
            result_reason=f"Alpaca {r.status_code}: {r.text[:200]}",
        )
        return None
    except Exception as e:
        print(f"  Alpaca simple buy exception: {e}")
        _emit_entry_audit_event(
            proposal=_proposal_options, result="failed",
            result_reason=f"broker exception: {type(e).__name__}: {e}",
        )
        return None


# ─── OCO exit (TP LIMIT + SL STOP paired) — for RECREATE_EXIT_PLAN ────────────

def place_oco_exit(symbol: str, qty: int, tp_price: float, sl_price: float,
                    side: str = "sell", client_order_id_prefix: str = "recreate-exit",
                    ) -> dict | None:
    """
    Place an OCO (One-Cancels-Other) exit order pair: LIMIT @ TP + STOP @ SL.
    When one fills, the other auto-cancels at the broker. GTC TIF — both
    orders survive across sessions (unlike bracket DAY children which
    expire at session close).

    Use case: `_do_recreate_exit_plan` in shared/remediation.py — restore
    exit protection for a position whose bracket children expired (DAY TIF).
    Replaces the previous behavior of `_do_recreate_exit_plan` which
    incorrectly market-closed the position. See
    `docs/INCIDENT-2026-05-22-positions-closed.md`.

    Args:
      symbol:     stock/ETF symbol (no slash for crypto — OCO not supported on crypto)
      qty:        number of shares (integer, > 0)
      tp_price:   take-profit limit price (absolute, must be on right side of mid)
      sl_price:   stop-loss stop price (absolute, must be on right side of mid)
      side:       "sell" for long exit, "buy_to_cover" for short exit
      client_order_id_prefix: prefix for client_order_id (timestamp appended)

    Returns Alpaca order JSON on success, None on failure.
    """
    if qty < 1 or tp_price <= 0 or sl_price <= 0:
        print(f"  oco reject: qty={qty} tp={tp_price} sl={sl_price}")
        return None
    if side not in ("sell", "buy_to_cover"):
        print(f"  oco reject: bad side '{side}' (must be sell|buy_to_cover)")
        return None

    # Sanity: for SELL exit (long position), tp > sl
    if side == "sell" and tp_price <= sl_price:
        print(f"  oco reject: SELL exit but tp ({tp_price}) <= sl ({sl_price})")
        return None
    if side == "buy_to_cover" and tp_price >= sl_price:
        print(f"  oco reject: BUY-TO-COVER exit but tp ({tp_price}) >= sl ({sl_price})")
        return None

    ts = int(time.time())
    coid = f"{client_order_id_prefix}-{symbol.replace('/','')}-{ts}"

    payload = {
        "symbol":         symbol,
        "qty":            str(int(qty)),
        "side":           side,
        "type":           "limit",
        "limit_price":    str(round(tp_price, 2)),
        "time_in_force":  "gtc",
        "order_class":    "oco",
        "stop_loss":      {"stop_price": str(round(sl_price, 2))},
        "client_order_id": coid,
    }

    # v3.32 — canonical ExecutionMode gate for OCO exit path.
    _gate = _execution_mode_precheck(
        intent="place_oco_exit",
        intended_notional_usd=float(qty) * float(tp_price),
        client_order_id=coid,
    )
    if _gate is not None:
        print(f"  OCO exit blocked by execution_mode: {_gate.get('reason','')[:150]}")
        return None
    try:
        r = requests.post(f"{ALPACA_BASE_URL}/v2/orders",
                           headers=_headers(), json=payload, timeout=10)
        if r.status_code in (200, 201):
            data = r.json()
            print(f"  OCO exit placed {symbol}: TP ${tp_price:.2f} / SL ${sl_price:.2f} "
                  f"id={data.get('id','?')[:8]}")
            return data
        print(f"  Alpaca OCO error {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        print(f"  Alpaca OCO exception: {e}")
        return None


def _fetch_single_position(symbol: str) -> dict | None:
    """GET /v2/positions/{symbol} — returns position dict or None if not found."""
    try:
        # URL-encode symbol (crypto BTC/USD → BTC%2FUSD)
        from urllib.parse import quote
        r = requests.get(f"{ALPACA_BASE_URL}/v2/positions/{quote(symbol, safe='')}",
                          headers=_headers(), timeout=10)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


def _cancel_open_orders_for_symbol(symbol: str) -> dict:
    """
    Cancel any open orders for `symbol` so a subsequent close can fill.

    v3.11.3 (2026-05-30): added to fix the bracket-interlock bug observed
    in production 2026-05-29 14:11-14:21 UTC. When a position has an
    active bracket OCO (LIMIT TP + STOP SL children), all of its qty is
    `held_for_orders` — Alpaca returns 403 "insufficient qty available"
    for any new SELL. The fix is to cancel the bracket children FIRST,
    then place the protective close.

    Approach:
      1. GET /v2/orders?symbols=X&status=open&nested=true&limit=100 —
         returns parent bracket orders with .legs[] children.
      2. For each parent + each leg whose `symbol` matches → DELETE
         /v2/orders/{order.id} (DELETE on the parent cancels children
         atomically; we also iterate legs explicitly as a safety belt
         in case parent DELETE is silently no-op for non-OCO orders).

    Returns dict:
      {
        "checked":  int   – orders inspected
        "canceled": list  – order_ids successfully canceled
        "failed":   list  – {order_id, status, reason} for non-2xx
        "error":    str | None – fatal error (network/auth)
      }

    Fail-soft: caller decides whether cancel-failure should block close.
    For protective closes the right behavior is "still try the close" —
    Alpaca's 403 will surface as a clean reason and the audit captures it.
    """
    from urllib.parse import quote
    result: dict = {"checked": 0, "canceled": [], "failed": [], "error": None}
    if not symbol:
        result["error"] = "empty symbol"
        return result
    if not _headers().get("APCA-API-KEY-ID"):
        result["error"] = "no_credentials"
        return result

    try:
        r = requests.get(
            f"{ALPACA_BASE_URL}/v2/orders",
            headers=_headers(),
            params={
                "status": "open",
                "symbols": symbol,
                "nested": "true",
                "limit": 100,
                "direction": "desc",
            },
            timeout=10,
        )
        if r.status_code != 200:
            result["error"] = f"list orders HTTP {r.status_code}: {r.text[:120]}"
            return result
        orders = r.json() if r.text else []
    except Exception as e:
        result["error"] = f"list orders exception: {type(e).__name__}: {e}"
        return result

    # Collect every order id whose own symbol or whose leg symbols match.
    # Parent cancellation cascades to legs on Alpaca's side, but we keep
    # an explicit dedup set to avoid double DELETE noise.
    sym_upper = (symbol or "").upper()
    to_cancel: list[str] = []
    seen: set = set()
    for o in orders:
        if not isinstance(o, dict):
            continue
        oid = o.get("id")
        osym = (o.get("symbol") or "").upper()
        legs = o.get("legs") or []
        leg_syms = [(l.get("symbol") or "").upper() for l in legs if isinstance(l, dict)]
        matches = (osym == sym_upper) or (sym_upper in leg_syms)
        if oid and matches and oid not in seen:
            to_cancel.append(oid)
            seen.add(oid)

    result["checked"] = len(to_cancel)

    # v3.32 — canonical ExecutionMode gate covers DELETE cancellations.
    # The check runs once for the entire cancel batch. Idempotency key
    # for cancel is per-symbol (deterministic).
    if to_cancel:
        _gate = _execution_mode_precheck(
            intent="cancel_open_orders_for_symbol",
            intended_notional_usd=0.0,
            client_order_id=f"cancel-{symbol}-{len(to_cancel)}",
        )
        if _gate is not None:
            result["error"] = f"execution_mode blocked: {_gate.get('reason','')[:180]}"
            return result

    for oid in to_cancel:
        try:
            d = requests.delete(
                f"{ALPACA_BASE_URL}/v2/orders/{quote(oid, safe='')}",
                headers=_headers(),
                timeout=10,
            )
            if d.status_code in (200, 204, 207):
                result["canceled"].append(oid)
            elif d.status_code == 404:
                # Already gone (race with broker fill / earlier cancel) — count as cancel
                result["canceled"].append(oid)
            else:
                result["failed"].append({
                    "order_id": oid,
                    "status": d.status_code,
                    "reason": d.text[:120],
                })
        except Exception as e:
            result["failed"].append({
                "order_id": oid,
                "status": 0,
                "reason": f"{type(e).__name__}: {e}",
            })
    return result


# ─── v3.9.10 (2026-05-27): safe_close() — single entry point for ALL SELL paths ─

def safe_close(
    symbol: str,
    intent_qty: float,
    *,
    intent_side: str = "sell",
    reason_tag: str = "alloc-exit",
    order_type: str = "market",
    limit_price: float | None = None,
    time_in_force: str = "day",
    is_crypto: bool = False,
    allow_market: bool = True,
    drift_threshold_pct: float = 0.05,
    cancel_brackets_first: bool = True,
) -> dict:
    """
    SINGLE entry point for all SELL/EXIT/buy_to_cover orders.

    INVARIANT (enforced architecturally — v3.9.10):
    Every order that REDUCES a position's notional MUST go through this function.
    Direct `requests.post(/v2/orders, side=sell)` is FORBIDDEN outside this
    function and is enforced by `tests/architecture/test_no_naked_sell.py`
    (CI lint test, AST-walk of repo).

    Rationale: between 2026-05-22 and 2026-05-27 we had THREE incidents of the
    same class — system sending SELL orders to positions that no longer
    existed (closed by bracket SL, or never present). Result: naked SHORTs,
    MARKET-closed healthy positions, $1,440 intraday loss + ~$16k naked
    short exposure on 2026-05-27 (NOW). Each fix was a point-fix in a
    different callsite; root cause was decentralized SELL emission.

    Behavior contract:
    1. Pre-flight: fetch live position via _fetch_single_position.
    2. 404 / qty=0 → return status="skipped" reason="position_gone"
    3. side mismatch (intent=sell, live=short) → return status="skipped"
    4. qty drift > drift_threshold_pct → use live qty (broker is truth)
    5. order_type="market" requires allow_market=True (default True for
       compat; future Layer-5 work can flip default to False for safety)
    6. Emit audit JSONL event (CLOSE_POSITION / EMERGENCY_CLOSE) BEFORE
       and AFTER the broker call
    7. Return dict with status / reason / alpaca_order_id / live_qty_used

    Args:
        symbol:             ticker (URL-encoded internally for crypto)
        intent_qty:         planned qty to close (will be clamped to live_qty)
        intent_side:        "sell" (long close) / "buy" (short cover) — default sell
        reason_tag:         client_order_id prefix (e.g. "alloc-exit",
                            "exit-emergency", "remediation-recreate")
        order_type:         "market" | "limit"
        limit_price:        required if order_type="limit"
        time_in_force:      "day" | "gtc" | "ioc"
        is_crypto:          True for crypto/USD pairs (qty=6 decimals, no day TIF)
        allow_market:       MARKET orders permitted (default True for now)
        drift_threshold_pct: 0.05 = 5% — if |plan_qty - live_qty|/plan_qty > this,
                            use live_qty
        cancel_brackets_first: v3.11.3 (2026-05-30) default True.
                            Before placing the close, GET open orders for `symbol`
                            and DELETE any that match (bracket parent +
                            OCO children). Fixes the 2026-05-29 incident
                            where 6 governor-driven safe_close calls all
                            returned Alpaca 403 because bracket children
                            held the entire qty (`held_for_orders=N`).
                            Crypto skips (no Alpaca crypto OCO support).
                            Fail-soft: cancel error does NOT block close —
                            the subsequent Alpaca 403 will surface as a
                            clean reason in the audit JSONL.
    Returns:
        {
          "status": "placed" | "skipped" | "failed" | "blocked",
          "reason": str,
          "alpaca_order_id": Optional[str],
          "live_qty": Optional[float],
          "intent_qty": float,
          "actual_qty": Optional[float],
          "brackets_canceled": list[str],   # v3.11.3 — order ids canceled
          "brackets_failed":   list[dict],  # v3.11.3 — {order_id,status,reason}
          "brackets_checked":  int,         # v3.11.3 — orders inspected
        }
    """
    # v3.10.2 (2026-05-27) — paper-only invariant via shared.autonomy.
    # Was undefined NameError on CI Python 3.11 (skipped lokalnie 3.9).
    try:
        from autonomy import assert_paper_only as _assert_paper
    except ImportError:
        from shared.autonomy import assert_paper_only as _assert_paper  # type: ignore
    _assert_paper(ALPACA_BASE_URL)

    # ── v3.30 HARD-WIRE: broker-repair-required precondition. ─────────────
    # Production retry-storm leak diagnosed 2026-06-16: 5 callsites
    # invoke ``safe_close`` but only ONE (exit-monitor lifecycle path)
    # checked ``retry_storm_containment.should_skip_broker_call`` before
    # the call. The other 4 callsites (exit-monitor POST fallback,
    # options-exit-monitor, allocator REDUCE, allocator EXIT) leaked
    # straight through to Alpaca even when ``broker_repair_required``
    # had quarantined the symbol. This is the single point that
    # protects ALL callsites at once.
    #
    # Behavior: refuse-and-return BEFORE the existing position fetch /
    # cancel-brackets / submit-order calls below. NO new broker call
    # is placed; we simply skip the broker call that would have
    # otherwise happened on the next line.
    #
    # Fail-soft: import failure or runtime exception does NOT crash
    # safe_close — we want a missing guard to fail OPEN (audit-only
    # absence) rather than fail CLOSED (block every close including
    # safe ones).
    try:
        try:
            from broker_repair_required import is_repair_required as _v3300_is_repair  # type: ignore
            from broker_repair_required import mark_repair_required as _v3300_mark_repair  # type: ignore
        except ImportError:
            from shared.broker_repair_required import is_repair_required as _v3300_is_repair  # type: ignore
            from shared.broker_repair_required import mark_repair_required as _v3300_mark_repair  # type: ignore
        if _v3300_is_repair(symbol):
            # Audit row — operator must see what we just refused. We bypass
            # ``make_decision`` here because the autonomy module's
            # whitelist enforces the union of allowed decision_types and
            # ``REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE`` is a containment-
            # layer signal (same shape as ``retry_storm_containment.
            # emit_skip_audit``). We append a raw JSONL row directly so
            # the row format stays consistent with the other v3.28
            # containment audit rows.
            try:
                try:
                    from retry_storm_containment import emit_skip_audit as _v3300_emit_skip  # type: ignore
                except ImportError:
                    from shared.retry_storm_containment import emit_skip_audit as _v3300_emit_skip  # type: ignore
                _v3300_emit_skip(symbol, incident_type="P13_BRACKET_INTERLOCK")
            except Exception:
                pass
            return {
                "status":           "REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE",
                "reason":           (
                    f"broker_repair_required quarantine for {symbol} — "
                    f"operator must clear via marker file"
                ),
                "alpaca_order_id":  None,
                "live_qty":         None,
                "intent_qty":       float(intent_qty),
                "actual_qty":       None,
                "broker_called":    False,
                "brackets_canceled": [],
                "brackets_failed":   [],
                "brackets_checked":  0,
                "symbol":           symbol,
            }
    except Exception:
        # Fail-soft per contract: guard absence must not crash closes.
        # Set the mark helper to a no-op so the 403 handler below
        # cannot trip a NameError; the call still proceeds.
        def _v3300_mark_repair(*a, **kw):  # type: ignore
            return None

    result: dict = {
        "status": "failed",
        "reason": "init",
        "alpaca_order_id": None,
        "live_qty": None,
        "intent_qty": float(intent_qty),
        "actual_qty": None,
    }

    intent_side_norm = (intent_side or "").lower()
    if intent_side_norm not in ("sell", "buy"):
        result["status"] = "blocked"
        result["reason"] = f"safe_close: invalid intent_side {intent_side!r} (must be sell/buy)"
        return result

    if order_type == "market" and not allow_market:
        result["status"] = "blocked"
        result["reason"] = "safe_close: MARKET orders disabled (allow_market=False)"
        return result

    # --- INVARIANT 1: live position MUST exist ---
    try:
        live_pos = _fetch_single_position(symbol)
    except Exception as e:
        result["status"] = "failed"
        result["reason"] = f"safe_close: position fetch error {type(e).__name__}: {e}"
        return result

    if not live_pos:
        result["status"] = "skipped"
        result["reason"] = f"safe_close: position {symbol} not found (404) — already closed"
        return result

    try:
        live_qty = abs(float(live_pos.get("qty") or 0))
        live_side = (live_pos.get("side") or "").lower()
    except (ValueError, TypeError) as e:
        result["status"] = "failed"
        result["reason"] = f"safe_close: malformed position data ({e})"
        return result

    result["live_qty"] = live_qty

    if live_qty <= 0:
        result["status"] = "skipped"
        result["reason"] = f"safe_close: live qty=0 (intent={intent_qty}) — position already closed"
        return result

    # --- INVARIANT 2: side compatibility ---
    # intent=sell expects long position; intent=buy expects short position
    if intent_side_norm == "sell" and live_side == "short":
        result["status"] = "skipped"
        result["reason"] = f"safe_close: intent=sell but position is SHORT (would double-short)"
        return result
    if intent_side_norm == "buy" and live_side == "long":
        result["status"] = "skipped"
        result["reason"] = f"safe_close: intent=buy_to_cover but position is LONG (no short to cover)"
        return result

    # --- INVARIANT 3: drift handling — broker is source of truth ---
    intent_qty_abs = abs(float(intent_qty))
    if intent_qty_abs <= 0:
        # User intends "close fully" — use live qty
        actual_qty = live_qty
    else:
        drift_pct = abs(live_qty - intent_qty_abs) / max(intent_qty_abs, 1)
        if drift_pct > drift_threshold_pct:
            # Clamp to live qty (never over-sell)
            actual_qty = min(intent_qty_abs, live_qty)
        else:
            actual_qty = min(intent_qty_abs, live_qty)

    if actual_qty <= 0:
        result["status"] = "skipped"
        result["reason"] = f"safe_close: actual_qty=0 after clamp"
        return result

    result["actual_qty"] = actual_qty

    # --- v3.11.3 (2026-05-30): cancel bracket OCO children FIRST ---
    # Production incident 2026-05-29 14:11-14:21 UTC: 6 governor-driven
    # safe_close calls all failed with Alpaca 403 "insufficient qty
    # available; held_for_orders=N" because positions had active bracket
    # children holding the entire qty. Protective mechanism armed but
    # could not fire. Default True so every protective/exit close
    # attempts cancellation first. Crypto skip — Alpaca crypto orders
    # are not OCO-bracketed.
    if cancel_brackets_first and not is_crypto:
        try:
            co = _cancel_open_orders_for_symbol(symbol)
            result["brackets_canceled"] = co["canceled"]
            result["brackets_failed"]   = co["failed"]
            result["brackets_checked"]  = co["checked"]
            if co["error"]:
                # Best-effort: print and proceed (Alpaca 403 below will
                # produce a clean reason if cancel failed and brackets
                # still hold qty).
                print(f"  safe_close({symbol}): cancel-brackets {co['error']} — proceeding")
        except Exception as e:
            result["brackets_canceled"] = []
            result["brackets_failed"]   = [{"order_id": None, "status": 0, "reason": str(e)[:80]}]
            print(f"  safe_close({symbol}): cancel-brackets exception {type(e).__name__}: {e}")
    else:
        result["brackets_canceled"] = []
        result["brackets_failed"]   = []
        result["brackets_checked"]  = 0

    # --- Build payload ---
    payload: dict = {
        "symbol": symbol,
        "side": intent_side_norm,
        "type": order_type,
        "time_in_force": "gtc" if is_crypto else time_in_force,
        "client_order_id": _client_order_id(reason_tag, symbol),
    }
    if is_crypto:
        payload["qty"] = str(round(actual_qty, 6))
    else:
        payload["qty"] = str(max(int(actual_qty), 1))
    if order_type == "limit":
        if limit_price is None or limit_price <= 0:
            result["status"] = "failed"
            result["reason"] = "safe_close: limit_price required for order_type=limit"
            return result
        payload["limit_price"] = str(round(limit_price, 4 if is_crypto else 2))

    # v3.32 — canonical ExecutionMode gate at the SINGLE close entry point.
    # This is the last-mile block: even if v3.30 broker_repair_required or
    # the pre-execute broker-repair check passed, the ExecutionMode gate
    # must still authorize before the POST fires. Fail-closed by design.
    _gate_coid = payload.get("client_order_id") or _client_order_id(
        "safe-close", str(symbol)
    )
    payload["client_order_id"] = _gate_coid
    _gate = _execution_mode_precheck(
        intent="safe_close",
        intended_notional_usd=float(payload.get("qty", 0) or 0) *
                              float(limit_price or 0.0 if order_type == "limit" else 0.0),
        client_order_id=_gate_coid,
    )
    if _gate is not None:
        result["status"] = "EXECUTION_MODE_BLOCKED"
        result["reason"] = _gate.get("reason", "execution_mode denied safe_close")
        result["broker_called"] = False
        return result
    # --- Submit order ---
    try:
        r = requests.post(
            f"{ALPACA_BASE_URL}/v2/orders",
            headers=_headers(),
            json=payload,
            timeout=15,
        )
    except Exception as e:
        result["status"] = "failed"
        result["reason"] = f"safe_close: POST exception {type(e).__name__}: {e}"
        return result

    if r.status_code in (200, 201):
        try:
            resp_j = r.json()
            result["status"] = "placed"
            result["alpaca_order_id"] = resp_j.get("id")
            result["reason"] = f"safe_close: {intent_side_norm} {payload['qty']} {order_type}"
        except Exception:
            result["status"] = "placed"
            result["reason"] = f"safe_close: placed but response unparseable"
    else:
        result["status"] = "failed"
        result["reason"] = f"safe_close: Alpaca {r.status_code}: {r.text[:120]}"
        # ── v3.30 HARD-WIRE: on broker-side state divergence, mark the ────
        # symbol repair-required so the next call from any caller is
        # short-circuited by the precondition guard above. Triggers:
        # 403 insufficient balance / held_for_orders, 422 qty must
        # be > 0 (live qty already drained), 422 insufficient qty.
        # Fail-soft: mark error never blocks the close result return.
        try:
            _text_lc = (r.text or "").lower()
            _is_state_divergence = (
                r.status_code == 403 and (
                    "insufficient" in _text_lc or "held_for_orders" in _text_lc
                )
            ) or (
                r.status_code == 422 and (
                    "qty must be" in _text_lc or "insufficient" in _text_lc
                )
            )
            if _is_state_divergence:
                _v3300_mark_repair(
                    symbol,
                    incident_type="P13_BRACKET_INTERLOCK",
                    error=f"safe_close Alpaca {r.status_code}: {r.text[:160]}",
                    manual_action_required=(
                        "Operator must (1) reconcile broker-side position "
                        "vs internal state, (2) cancel any orphan brackets, "
                        "(3) create operator marker, (4) call "
                        "broker_repair_required.clear_repair()."
                    ),
                    safe_mode_reason=(
                        f"safe_close({symbol}) returned {r.status_code} "
                        f"state-divergence — quarantine until operator clears"
                    ),
                )
        except Exception:
            pass

    # --- Emit audit JSONL event (Layer 5 visibility) ---
    try:
        try:
            from autonomy import make_decision
            from audit import write_audit_event
        except ImportError:
            from shared.autonomy import make_decision  # type: ignore
            from shared.audit import write_audit_event  # type: ignore
        d = make_decision(
            decision_type="CLOSE_POSITION" if reason_tag != "exit-emergency" else "EMERGENCY_CLOSE",
            decision="PLACED" if result["status"] == "placed" else "SKIPPED" if result["status"] == "skipped" else "FAILED",
            reason=result["reason"],
            actor="safe_close",
            affected_symbols=[symbol],
            inputs={
                "intent_qty": result["intent_qty"],
                "live_qty": result["live_qty"],
                "actual_qty": result["actual_qty"],
                "intent_side": intent_side_norm,
                "order_type": order_type,
                "reason_tag": reason_tag,
                # v3.11.3: surface bracket cancellation for forensic visibility
                "brackets_canceled": result.get("brackets_canceled", []),
                "brackets_failed":   result.get("brackets_failed",   []),
            },
            action_taken=f"{intent_side_norm} {actual_qty} {order_type}",
            result=result["status"],
            reversible=False,
        )
        write_audit_event(d, kind="trading")
    except Exception as audit_err:
        # Audit failure must NEVER block order placement (defensive)
        print(f"  safe_close audit emit failed (non-fatal): {audit_err}")

    return result


# ─── High-level signal-to-order adapter ───────────────────────────────────────

def execute_stock_signal(signal: dict) -> dict | None:
    """
    Convert a monitor's signal dict into a bracket order via Alpaca.

    Expected `signal` shape (matches what monitors produce today):
      {
        "symbol":      "RTX",
        "action":      "BUY" | "SELL_SHORT",
        "size_usd":    8000,
        "stop_loss":   absolute_price OR None (then we use sl_pct),
        "take_profit": absolute_price OR None,
        "sl_pct":      e.g. -5.0  (used when stop_loss is None)
        "tp_pct":      e.g. +12.0
        "strategy":    name string
      }

    Returns Alpaca order on success, None on any failure (caller falls
    through to email-only logging).
    """
    sym       = signal["symbol"]
    action    = signal["action"]
    size_usd  = float(signal.get("size_usd", 0))
    strategy  = signal.get("strategy", "auto")

    if size_usd <= 0:
        print(f"  {sym}: size_usd={size_usd} -> skip")
        return None

    # Per-instrument trading window gate (v3.2 — single source of truth in
    # config/instrument_windows.json). Checks (1) per-symbol pause and
    # (2) market hours. Replaces the old inline is_us_market_open call.
    try:
        from instrument_windows import can_trade_now
    except ImportError:
        from shared.instrument_windows import can_trade_now
    ok, reason = can_trade_now(sym, asset_class="us_equity")
    if not ok:
        print(f"  {sym}: trade-window blocked — {reason}")
        return {"deferred": True, "reason": reason, "symbol": sym}

    side = "buy" if action.upper() == "BUY" else "sell_short"

    # If signal already has absolute SL/TP, use them. Else compute from %.
    sl_abs = signal.get("stop_loss")
    tp_abs = signal.get("take_profit")
    entry  = None

    # v3.8.9 (2026-05-21): aggressive entry pricing — buy at ask, sell at bid.
    # LLM-flagged 2026-05-19: fill_rate.unknown 37% (16 cancelled / 30 placed)
    # avg_cancel=82.4 min — geo-USO/OXY/GLD LIMITs placed at q["mid"] sat
    # in queue 80+ min then expired. For 24/7-news-driven entries (geo /
    # defense / twitter / reddit) we prefer guaranteed fill over 0.5×spread
    # price improvement. Stocks/ETFs spread ~0.01-0.05 typically → cost is
    # negligible vs missed fills.
    def _aggressive_entry(quote: dict, side_: str) -> float:
        if side_ == "buy":
            return float(quote.get("ask") or quote.get("mid"))
        return float(quote.get("bid") or quote.get("mid"))

    if sl_abs and tp_abs:
        # Need a fresh entry price. Use ask (BUY) / bid (SHORT) for aggressive fill.
        q = get_latest_quote(sym)
        if not q:
            print(f"  {sym}: quote unavailable -> skip")
            return None
        entry = _aggressive_entry(q, side)
    else:
        # Fallback path: SL/TP given as percentages
        sl_pct = float(signal.get("sl_pct", 0))
        tp_pct = float(signal.get("tp_pct", 0))
        if not sl_pct or not tp_pct:
            print(f"  {sym}: missing SL/TP -> skip")
            return None
        q = get_latest_quote(sym)
        if not q:
            print(f"  {sym}: quote unavailable -> skip")
            return None
        # v3.8.9: aggressive fill — ask for BUY, bid for SHORT. SL/TP still
        # computed relative to entry, so % thresholds preserved.
        entry = _aggressive_entry(q, side)
        if side == "buy":
            sl_abs = entry * (1 + sl_pct / 100.0)   # sl_pct is negative
            tp_abs = entry * (1 + tp_pct / 100.0)
        else:
            sl_abs = entry * (1 - sl_pct / 100.0)
            tp_abs = entry * (1 - tp_pct / 100.0)

    qty = max(1, int(size_usd / entry))

    return place_stock_bracket(
        symbol      = sym,
        side        = side,
        qty         = qty,
        entry_price = entry,
        stop_loss   = round(sl_abs, 2),
        take_profit = round(tp_abs, 2),
        strategy    = strategy,
        # v3.14.0 (2026-06-02) — forward confidence_inputs through (closes CONF-002).
        confidence_inputs = signal.get("confidence_inputs"),
    )


def execute_crypto_signal(signal: dict) -> dict | None:
    """
    Crypto entry: simple limit at mid. SL/TP managed by exit-monitor
    crypto thresholds (Alpaca crypto = no bracket support).
    """
    sym      = signal["symbol"]
    action   = signal["action"]
    size_usd = float(signal.get("size_usd", 0))
    strategy = signal.get("strategy", "crypto-momentum")

    if size_usd <= 0:
        return None

    # v3.8.1 (2026-05-15): Alpaca paper crypto is LONG-only. SELL_SHORT
    # signals get rejected with 403 "insufficient balance for X". Reject
    # upstream so caller's notify_signal gets a clean reason instead of
    # propagating the rejection through to a generic "Alert NOT sent
    # (error)" email. The crypto-monitor v3.8.1 gates emission at source,
    # but this is a belt-and-braces second line for any other caller.
    if action.upper() in ("SELL_SHORT", "SHORT"):
        print(f"  {sym}: SELL_SHORT crypto not supported (Alpaca paper LONG-only) — refusing")
        return {"deferred": True, "reason": "crypto_no_short", "symbol": sym}

    # Per-instrument trading window gate. Crypto is 24/7 so default-allow,
    # but per-symbol pause (instrument_overrides) still applies.
    try:
        from instrument_windows import can_trade_now
    except ImportError:
        from shared.instrument_windows import can_trade_now
    ok, reason = can_trade_now(sym, asset_class="crypto")
    if not ok:
        print(f"  {sym}: trade-window blocked — {reason}")
        return {"deferred": True, "reason": reason, "symbol": sym}

    side = "buy" if action.upper() in ("BUY", "BUY_TO_OPEN") else "sell"

    q = get_latest_crypto_quote(sym)
    if not q:
        print(f"  {sym}: crypto quote unavailable -> skip")
        return None
    entry = q["mid"]
    qty = round(size_usd / entry, 4)
    if qty <= 0:
        return None

    return place_crypto_order(
        symbol      = sym,
        side        = side,
        qty         = qty,
        limit_price = entry,
        strategy    = strategy,
        # v3.14.0 (2026-06-02) — forward confidence_inputs through (closes CONF-002).
        confidence_inputs = signal.get("confidence_inputs"),
    )
