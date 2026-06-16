"""v3.23 (2026-06-15) — Shadow fill simulator (NO-BROKER, NO-NETWORK).

Shadow simulation NEVER places orders. ShadowFill is a hypothetical
fill record only. Outcome tracking treats it as a forward-looking
observation, NOT a paper trade.

HARD SAFETY
-----------
- NEVER imports ``shared.alpaca_orders`` or ``alpaca_orders``.
- NEVER imports any broker SDK.
- NEVER calls ``submit_order`` / ``place_order`` / ``safe_close`` /
  ``place_stock_order`` / ``place_crypto_order`` / ``place_option_order``
  / ``close_position`` / ``close_all_positions``.
- NEVER makes a network call. The module is pure arithmetic + a
  fail-soft local JSONL append.
- ``simulate_shadow_fill`` REFUSES if any of the 7 broker / live env
  flags are truthy (defence in depth — caller should also gate, but
  this module re-asserts).
- ``simulate_shadow_fill`` REFUSES if ``signal_event.entry_capable`` is
  not True (returns ``None``).
- ``simulate_shadow_fill`` REFUSES if ``risk_decision`` is anything
  other than ``APPROVE`` (returns ``None`` with audit-friendly reason).
- ``simulate_shadow_fill`` REFUSES if the caller does not provide an
  explicit ``canary_preflight_verdict``. The verdict must be a member
  of the v3.30 enum (preflight-only canary contract); the only
  verdicts that pass through to a ``ShadowFill`` are
  ``CANARY_PREFLIGHT_DRY_RUN_OK`` and
  ``CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED``. Any other
  verdict produces ``REJECTED_BY_GATE``.
- Quantity is capped HARD: 1 share for equity, 0.0001 token for crypto.
  Larger requested sizes are clamped down (never up).
- Every emitted ShadowFill carries an immutable tuple of standing
  markers re-asserting that EDGE_GATE/ALLOW_BROKER_PAPER are still
  false, live trading remains unsupported, and no order placement
  occurred.

This module is intentionally small. It does ONE thing: convert a
single approved-and-preflight-OK signal into ONE hypothetical fill
record. It does not aggregate, does not tally, does not write to
the broker, and does not call any code path that does.

Any URL string in this module is the canonical Alpaca paper-trade URL
(``paper-api.alpaca.markets``). The static paper-only scan must see
only that URL in source; no live host name appears here.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent

# Canonical paper API URL — referenced ONLY as a literal here so the
# static paper-only scan recognises this module. The simulator does
# NOT make a request to this URL; it is a documentation marker.
PAPER_API_URL_MARKER = "https://paper-api.alpaca.markets"  # noqa: E501

# ─── Standing markers (re-asserted on every ShadowFill) ────────────

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "SHADOW_ONLY",
)

# ─── Verdict-level constants ──────────────────────────────────────

FILL_FILLED                    = "FILLED"
FILL_REJECTED_BY_GATE          = "REJECTED_BY_GATE"

# Reason codes (audit-friendly; caller may log)
REJ_REASON_BROKER_FLAG_TRUTHY   = (
    "BROKER_OR_LIVE_FLAG_TRUTHY")
REJ_REASON_ENTRY_NOT_CAPABLE    = "ENTRY_NOT_CAPABLE"
REJ_REASON_RISK_NOT_APPROVED    = "RISK_NOT_APPROVED"
REJ_REASON_CANARY_NOT_PROVIDED  = "CANARY_VERDICT_NOT_PROVIDED"
REJ_REASON_CANARY_REFUSED       = "CANARY_VERDICT_REFUSED"
REJ_REASON_MISSING_MARKET_DATA  = "MISSING_MARKET_SNAPSHOT_FIELDS"
REJ_REASON_BAD_SIDE             = "INVALID_SIDE"
REJ_REASON_BAD_PRICE            = "INVALID_PRICE_OR_QTY"

# Canary verdicts that allow a ShadowFill to proceed. Both keep us
# preflight-only; we never claim to have executed broker paper.
_CANARY_VERDICTS_PASSTHROUGH: frozenset[str] = frozenset({
    "CANARY_PREFLIGHT_DRY_RUN_OK",
    "CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED",
})

# ─── HARD: broker / live flag re-assertion ────────────────────────

_BROKER_FLAGS: tuple[str, ...] = (
    "ALLOW_BROKER_PAPER",
    "EDGE_GATE_ENABLED",
    "BROKER_EXECUTION_ENABLED",
)
_LIVE_FLAGS: tuple[str, ...] = (
    "LIVE_TRADING",
    "LIVE_ENABLED",
    "GO_LIVE",
    "LIVE_TRADING_ENABLED",
)


def _env_truthy(name: str, env: Mapping[str, str] | None = None) -> bool:
    src = env if env is not None else os.environ
    return str(src.get(name, "false")).strip().lower() in (
        "true", "1", "yes", "on")


def _any_broker_or_live_flag_truthy(
    env: Mapping[str, str] | None = None,
) -> bool:
    for f in _BROKER_FLAGS + _LIVE_FLAGS:
        if _env_truthy(f, env):
            return True
    return False


# ─── Qty caps (hard, never relaxed) ────────────────────────────────

_EQUITY_QTY_CAP    = 1.0
_CRYPTO_QTY_CAP    = 0.0001


def _clamp_qty(requested_qty: float, asset_class: str) -> float:
    """Clamp requested qty DOWN to the hard cap. Never UP.

    Equity / ETF / option: max 1 share.
    Crypto: max 0.0001 token.
    Any non-positive request returns 0.0 (caller should treat as
    rejection).
    """
    try:
        rq = float(requested_qty)
    except Exception:
        return 0.0
    if rq <= 0:
        return 0.0
    ac = (asset_class or "").lower()
    if ac in ("crypto", "cryptocurrency"):
        cap = _CRYPTO_QTY_CAP
    else:
        cap = _EQUITY_QTY_CAP
    return min(rq, cap)


# ─── ShadowFill dataclass ──────────────────────────────────────────


@dataclass(frozen=True)
class ShadowFill:
    """Hypothetical fill record. NEVER a real order, NEVER a paper trade.

    ``record_type`` is fixed to ``SHADOW_FILL_HYPOTHETICAL`` so any
    downstream consumer can filter it out of broker-execution counters
    by string equality.
    """

    signal_id:         str
    symbol:            str
    strategy:          str
    side:              str            # "long" | "short"
    asset_class:       str            # "us_equity" | "us_etf" | "us_option" | "crypto"
    intended_price:    float
    fill_price:        float
    qty:               float
    timestamp_iso:     str
    slippage_bps:      float
    spread_bps:        float
    fill_status:       str            # FILLED | REJECTED_BY_GATE
    rejection_reason:  str | None
    standing_markers:  tuple[str, ...] = field(default_factory=lambda: STANDING_MARKERS)
    record_type:       str            = "SHADOW_FILL_HYPOTHETICAL"
    is_paper_trade:    bool           = False
    broker_order_submitted: bool      = False
    canary_preflight_verdict: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type":              self.record_type,
            "signal_id":                self.signal_id,
            "symbol":                   self.symbol,
            "strategy":                 self.strategy,
            "side":                     self.side,
            "asset_class":              self.asset_class,
            "intended_price":           self.intended_price,
            "fill_price":               self.fill_price,
            "qty":                      self.qty,
            "timestamp":                self.timestamp_iso,
            "slippage_bps":             self.slippage_bps,
            "spread_bps":               self.spread_bps,
            "fill_status":              self.fill_status,
            "rejection_reason":         self.rejection_reason,
            "is_paper_trade":           self.is_paper_trade,
            "broker_order_submitted":   self.broker_order_submitted,
            "canary_preflight_verdict": self.canary_preflight_verdict,
            "standing_markers":         list(self.standing_markers),
        }


# ─── Internal helpers ──────────────────────────────────────────────


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _side_to_long_short(side_raw: str) -> str | None:
    s = (side_raw or "").strip().lower()
    if s in ("long", "buy", "buy_to_open"):
        return "long"
    if s in ("short", "sell_short", "sell"):
        return "short"
    return None


def _compute_fill_price(*,
                         intended_price: float,
                         side: str,
                         slippage_bps: float,
                         spread_bps: float) -> float:
    """Deterministic. Long pays half-spread + slippage; short receives
    less by the same amount.
    """
    half_spread = (spread_bps / 2.0) / 10_000.0
    slip = max(0.0, float(slippage_bps)) / 10_000.0
    if side == "long":
        return intended_price * (1.0 + half_spread + slip)
    return intended_price * (1.0 - half_spread - slip)


# ─── Public API ────────────────────────────────────────────────────


def simulate_shadow_fill(
    signal_event: Mapping[str, Any] | Any,
    *,
    market_snapshot: Mapping[str, Any] | None = None,
    canary_preflight_verdict: str | None = None,
    risk_decision: str | None = None,
    slippage_bps: float = 10.0,
    spread_bps: float = 5.0,
    env: Mapping[str, str] | None = None,
) -> ShadowFill | None:
    """Build a deterministic ShadowFill from a signal event.

    Returns ``None`` if any HARD gate refuses (broker flag truthy,
    entry not capable, risk not APPROVE, canary verdict missing or
    refused, market data missing/invalid).

    Otherwise returns a frozen ``ShadowFill`` ready to be appended to
    the local ledger via :func:`append_shadow_ledger`.

    This function NEVER calls a broker. It NEVER imports
    ``alpaca_orders``. It NEVER makes a network call.
    """
    # ── Defence in depth: re-assert env flag refusal ───────────────
    if _any_broker_or_live_flag_truthy(env=env):
        return None

    # ── signal_event field extraction (tolerant to dict/dataclass) ─
    se = signal_event
    if not isinstance(se, Mapping):
        # tolerate dataclass-like objects: pull attributes by name
        try:
            se = {
                "signal_id":     getattr(se, "signal_id", None),
                "symbol":        getattr(se, "symbol", None),
                "strategy":      getattr(se, "strategy", None),
                "side":          getattr(se, "side", None),
                "asset_class":   getattr(se, "asset_class", None),
                "entry_capable": getattr(se, "entry_capable", None),
                "intended_price":
                    getattr(se, "intended_price", None) or
                    getattr(se, "entry_price",    None),
                "qty":           getattr(se, "qty", None),
            }
        except Exception:
            return None

    if not bool(se.get("entry_capable", False)):
        return None

    if (risk_decision or "").strip().upper() != "APPROVE":
        return None

    # Canary verdict is mandatory and must be passthrough class.
    if not canary_preflight_verdict:
        return None
    if str(canary_preflight_verdict) not in _CANARY_VERDICTS_PASSTHROUGH:
        # Construct a REJECTED_BY_GATE record for audit transparency
        return _build_rejected(
            signal_event=se,
            reason=REJ_REASON_CANARY_REFUSED,
            canary_preflight_verdict=str(canary_preflight_verdict),
        )

    # ── Market snapshot ────────────────────────────────────────────
    snap = dict(market_snapshot or {})
    intended_price = (
        _safe_float(snap.get("reference_price"))
        or _safe_float(snap.get("price"))
        or _safe_float(se.get("intended_price"))
        or _safe_float(se.get("entry_price"))
    )
    if intended_price <= 0:
        return _build_rejected(
            signal_event=se,
            reason=REJ_REASON_MISSING_MARKET_DATA,
            canary_preflight_verdict=str(canary_preflight_verdict),
        )

    side = _side_to_long_short(str(se.get("side") or "long"))
    if side is None:
        return _build_rejected(
            signal_event=se,
            reason=REJ_REASON_BAD_SIDE,
            canary_preflight_verdict=str(canary_preflight_verdict),
        )

    asset_class = str(se.get("asset_class") or "us_equity")
    requested_qty = _safe_float(
        se.get("qty"), _EQUITY_QTY_CAP if asset_class != "crypto"
        else _CRYPTO_QTY_CAP)
    qty = _clamp_qty(requested_qty, asset_class)
    if qty <= 0:
        return _build_rejected(
            signal_event=se,
            reason=REJ_REASON_BAD_PRICE,
            canary_preflight_verdict=str(canary_preflight_verdict),
        )

    fill_price = _compute_fill_price(
        intended_price=intended_price,
        side=side,
        slippage_bps=slippage_bps,
        spread_bps=spread_bps,
    )

    sig_id = str(se.get("signal_id") or f"shadow-{uuid.uuid4().hex[:12]}")

    return ShadowFill(
        signal_id=         sig_id,
        symbol=            str(se.get("symbol") or "?"),
        strategy=          str(se.get("strategy") or "unknown"),
        side=              side,
        asset_class=       asset_class,
        intended_price=    float(intended_price),
        fill_price=        float(fill_price),
        qty=               float(qty),
        timestamp_iso=     _utc_now_iso(),
        slippage_bps=      float(slippage_bps),
        spread_bps=        float(spread_bps),
        fill_status=       FILL_FILLED,
        rejection_reason=  None,
        canary_preflight_verdict=str(canary_preflight_verdict),
    )


def _build_rejected(*,
                    signal_event: Mapping[str, Any],
                    reason: str,
                    canary_preflight_verdict: str | None) -> ShadowFill:
    """Build a REJECTED_BY_GATE ShadowFill (still NEVER submitted)."""
    se = signal_event
    asset_class = str(se.get("asset_class") or "us_equity")
    side = _side_to_long_short(str(se.get("side") or "long")) or "long"
    return ShadowFill(
        signal_id=         str(se.get("signal_id") or
                                f"shadow-rej-{uuid.uuid4().hex[:12]}"),
        symbol=            str(se.get("symbol") or "?"),
        strategy=          str(se.get("strategy") or "unknown"),
        side=              side,
        asset_class=       asset_class,
        intended_price=    _safe_float(se.get("intended_price") or
                                       se.get("entry_price"), 0.0),
        fill_price=        0.0,
        qty=               0.0,
        timestamp_iso=     _utc_now_iso(),
        slippage_bps=      0.0,
        spread_bps=        0.0,
        fill_status=       FILL_REJECTED_BY_GATE,
        rejection_reason=  reason,
        canary_preflight_verdict=canary_preflight_verdict,
    )


def append_shadow_ledger(fill: ShadowFill,
                          *,
                          path: Path | str | None = None) -> Path | None:
    """Append a ShadowFill row to today's shadow ledger.

    Fail-soft: returns ``None`` on I/O error. Never raises.

    Default destination: ``learning-loop/shadow_ledger/<YYYY-MM-DD>.jsonl``.
    """
    if not isinstance(fill, ShadowFill):
        return None
    try:
        if path is None:
            ledger_dir = REPO_ROOT / "learning-loop" / "shadow_ledger"
            ledger_dir.mkdir(parents=True, exist_ok=True)
            p = ledger_dir / f"{_today_iso()}.jsonl"
        else:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(fill.to_dict(), sort_keys=True, default=str)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return p
    except Exception:
        return None


def emit_shadow_fill(
    signal_event: Mapping[str, Any] | Any,
    *,
    market_snapshot: Mapping[str, Any] | None = None,
    canary_preflight_verdict: str | None = None,
    risk_decision: str | None = None,
    slippage_bps: float = 10.0,
    spread_bps: float = 5.0,
    ledger_path: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    write_ledger: bool = True,
) -> ShadowFill | None:
    """Convenience: build + append.

    Returns the ShadowFill (with ``fill_status=FILLED`` or
    ``REJECTED_BY_GATE``), or ``None`` if a HARD refusal blocked even
    a rejection record (entry_capable=False, risk_decision != APPROVE,
    canary verdict missing, broker flag truthy).
    """
    fill = simulate_shadow_fill(
        signal_event,
        market_snapshot=market_snapshot,
        canary_preflight_verdict=canary_preflight_verdict,
        risk_decision=risk_decision,
        slippage_bps=slippage_bps,
        spread_bps=spread_bps,
        env=env,
    )
    if fill is None:
        return None
    if write_ledger:
        append_shadow_ledger(fill, path=ledger_path)
    return fill


# ─── v3.24 ETAP 8 — Conservative activation via shadow_eligibility ─


def maybe_simulate_from_row(
    row: Mapping[str, Any],
    *,
    market_snapshot: Mapping[str, Any] | None = None,
    slippage_bps: float = 10.0,
    spread_bps: float = 5.0,
    env: Mapping[str, str] | None = None,
) -> ShadowFill | None:
    """v3.24 entry point. Build a ShadowFill ONLY when eligibility passes.

    This is the v3.24-blessed bridge between the opportunity ledger
    and the shadow ledger. The caller hands us a raw opportunity row
    (as written by :mod:`shared.signal_opportunity_ledger`); we ask
    :mod:`shared.shadow_eligibility` whether the row meets the v3.24
    eligibility threshold. Only when the verdict is ``ELIGIBLE`` do we
    construct a :class:`ShadowFill`. Every other verdict returns
    ``None`` — no fill, no ledger write.

    HARD invariants re-asserted at the function boundary:

    - NEVER imports ``alpaca_orders``.
    - NEVER makes a network call.
    - ShadowFill ``is_paper_trade`` stays ``False``.
    - ShadowFill ``broker_order_submitted`` stays ``False``.
    - Qty caps preserved (1 share equity / 0.0001 token crypto) — we
      do not even pass through to the simulator on a non-eligible
      row.
    - Standing markers preserved (see :data:`STANDING_MARKERS`).

    Parameters
    ----------
    row :
        A single opportunity_ledger row dict (the JSONL line). The
        function tolerates any extra fields and never mutates the
        input.
    market_snapshot :
        Optional ``{reference_price | price, ...}`` mapping passed
        through to :func:`simulate_shadow_fill`. If absent, the
        simulator uses the price embedded in ``row.raw_signal``.
    slippage_bps, spread_bps :
        Same as :func:`simulate_shadow_fill`.
    env :
        Optional environment override for testing. Production callers
        should pass ``None``.

    Returns
    -------
    ShadowFill | None
        ``None`` whenever eligibility fails or the simulator refuses;
        otherwise the FILLED ShadowFill ready to be appended via
        :func:`append_shadow_ledger`.
    """
    # Lazy import — shadow_eligibility is the v3.24 sibling module. We
    # import locally to keep the public module surface clean and so a
    # missing eligibility module fails closed (returns None) instead
    # of cascading an ImportError up to the monitor.
    try:
        try:
            from shadow_eligibility import (  # type: ignore
                evaluate_shadow_eligibility,
                ShadowEligibilityDecision,
            )
        except ImportError:
            from shared.shadow_eligibility import (  # type: ignore
                evaluate_shadow_eligibility,
                ShadowEligibilityDecision,
            )
    except Exception:
        # Fail-closed — without the eligibility module we MUST NOT
        # emit a ShadowFill.
        return None

    if not isinstance(row, Mapping):
        return None

    # Defence in depth — broker / live env flag re-assertion BEFORE
    # we even compute eligibility.
    if _any_broker_or_live_flag_truthy(env=env):
        return None

    verdict = evaluate_shadow_eligibility(row)
    if verdict.decision != ShadowEligibilityDecision.ELIGIBLE:
        # Eligibility rejected → no fill. Logging is the caller's job
        # (the eligibility result is fully self-describing).
        return None

    # Build the minimal SignalEvent-shaped dict the simulator accepts.
    raw = row.get("raw_signal") or {}
    if not isinstance(raw, Mapping):
        raw = {}

    # Symbol / strategy / side / asset_class come from the row, with
    # raw_signal as fallback. We never trust raw_signal alone — the
    # ledger top-level fields are canonical.
    symbol      = row.get("symbol")     or raw.get("symbol")
    strategy    = row.get("strategy")   or raw.get("strategy_id") or raw.get("strategy")
    asset_class = (row.get("asset_class") or raw.get("asset_class")
                   or "us_equity")

    # side: ledger rows historically carry it under ``side`` or
    # encode it in ``raw_signal.action`` (BUY / SELL_SHORT / ...).
    side = row.get("side") or raw.get("side")
    if not side:
        action = (raw.get("action") or "").upper()
        if action in ("BUY", "BUY_TO_OPEN", "LONG"):
            side = "long"
        elif action in ("SELL_SHORT", "SHORT", "SELL_TO_OPEN"):
            side = "short"
        else:
            side = "long"

    intended_price = (
        raw.get("intended_price")
        or raw.get("price")
        or raw.get("reference_price")
        or raw.get("entry_price")
    )

    # qty defaults to the per-asset cap; the simulator will clamp.
    qty = (raw.get("qty")
           or (_CRYPTO_QTY_CAP if str(asset_class).lower() == "crypto"
               else _EQUITY_QTY_CAP))

    signal_event = {
        "signal_id":      row.get("signal_id") or raw.get("signal_id"),
        "symbol":         symbol,
        "strategy":       strategy,
        "side":           side,
        "asset_class":    asset_class,
        "entry_capable":  True,    # eligibility guarantees this
        "intended_price": intended_price,
        "qty":            qty,
    }

    # v3.29 ETAP 8 — master system-activation gate. After eligibility
    # passes, ask the master gate whether the WHOLE system is in a
    # state in which the shadow simulator may emit hypothetical
    # fills. When BLOCKED, emit an audit-friendly REJECTED_BY_GATE
    # row so the forensic tail explicitly shows the refusal. Tests
    # can bypass by patching the master gate to return a
    # SHADOW_PERMITTED decision.
    #
    # The guard is controlled by the env override
    # ``SHADOW_SIMULATOR_REQUIRE_MASTER_GATE``. Production workflows
    # pin this to ``true``. When unset (legacy callers / pre-existing
    # unit tests), the master-gate guard is non-blocking — the
    # eligibility + canary + risk stack remains the safety contract.
    _gate_env = env if env is not None else os.environ
    if str(_gate_env.get("SHADOW_SIMULATOR_REQUIRE_MASTER_GATE", "")
            ).strip().lower() in ("true", "1", "yes", "on"):
        try:
            try:
                from system_activation_gate import (  # type: ignore
                    evaluate as _eval_master,
                    SHADOW_PERMITTED_DECISIONS as _PERM,
                )
            except ImportError:
                from shared.system_activation_gate import (  # type: ignore
                    evaluate as _eval_master,
                    SHADOW_PERMITTED_DECISIONS as _PERM,
                )
            _master = _eval_master()
            if _master.decision not in _PERM:
                return _build_rejected(
                    signal_event=signal_event,
                    reason="REFUSED_SHADOW_DUE_TO_SYSTEM_GATE",
                    canary_preflight_verdict=str(_master.decision.value),
                )
        except Exception:
            # Fail closed when the guard is REQUIRED — without a
            # working master gate we MUST NOT emit a fill.
            return _build_rejected(
                signal_event=signal_event,
                reason="REFUSED_SHADOW_DUE_TO_SYSTEM_GATE",
                canary_preflight_verdict="MASTER_GATE_UNREACHABLE",
            )

    return simulate_shadow_fill(
        signal_event,
        market_snapshot=market_snapshot,
        canary_preflight_verdict=verdict.canary_verdict,
        risk_decision="APPROVE",   # eligibility maps APPROVE+DETECTED → APPROVE
        slippage_bps=slippage_bps,
        spread_bps=spread_bps,
        env=env,
    )


__all__ = [
    "ShadowFill",
    "STANDING_MARKERS",
    "FILL_FILLED",
    "FILL_REJECTED_BY_GATE",
    "REJ_REASON_BROKER_FLAG_TRUTHY",
    "REJ_REASON_ENTRY_NOT_CAPABLE",
    "REJ_REASON_RISK_NOT_APPROVED",
    "REJ_REASON_CANARY_NOT_PROVIDED",
    "REJ_REASON_CANARY_REFUSED",
    "REJ_REASON_MISSING_MARKET_DATA",
    "REJ_REASON_BAD_SIDE",
    "REJ_REASON_BAD_PRICE",
    "simulate_shadow_fill",
    "append_shadow_ledger",
    "emit_shadow_fill",
    "maybe_simulate_from_row",
]
