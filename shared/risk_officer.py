"""
Risk Officer — deterministic trade-validation gate.

Replaces the agent-based `.claude/agents/risk-officer.md` with a
synchronous Python check. Monitors call `evaluate_trade(proposal)`
BEFORE placing an order; APPROVE → place, REJECT → log + skip.

This consolidates checks that were previously scattered across
monitors and shared/risk_guards.py. The semantics mirror v2.0 of the
agent (default APPROVE, REJECT only on hard violations) so existing
strategies/*.md and STRATEGY.md continue to be the source of truth.

Hard checks (any fail → REJECT):
  1. ticker on whitelist (.claude/rules/tickers-whitelist.md)
  2. size_usd ≤ 20% of equity
  3. stop_loss provided + numeric
  4. R:R ≥ 1.2 (TP-distance / SL-distance from entry)
  5. per-ticker total exposure ≤ 40% equity (uses
     shared.risk_guards.concentration_ok)
  6. daily P&L > -12% (uses shared.risk_guards.daily_drawdown_guard)
  7. VIX < 60 (uses shared.risk_guards.vix_guard)

Soft warnings (don't block — annotated in `warnings`):
  - R:R in [1.2, 1.5]
  - size_usd > 15% equity
  - ticker already > 25% portfolio post-trade

Fail-open contract: if any external dependency (Alpaca, VIX source) is
unavailable, the check is logged as `unavailable` and skipped — REJECT
is reserved for explicit rule violations the system can verify, never
for missing data.

Env override:
  USE_RISK_OFFICER=false  →  evaluate_trade always returns APPROVE.
                              Useful for backtests or emergency bypass.
"""

from __future__ import annotations

import os
from typing import Any

from risk_guards import (   # noqa: E402 — same-dir import (monitors path-insert shared/)
    vix_guard, daily_drawdown_guard, concentration_ok,
    get_account_status,
)


# ─── Whitelist (mirrors .claude/rules/tickers-whitelist.md) ───────────────────

_WHITELIST: set[str] = {
    # Mega-cap
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    # Financials
    "JPM", "V", "MA", "JNJ", "BRK.B",
    # Broad ETFs
    "SPY", "QQQ", "VOO", "VTI", "IWM", "VXUS", "VWO",
    # Sector ETFs
    "XLK", "XLF", "XLE", "XLV", "XLY",
    # Commodity ETFs
    "GLD", "SLV",
    # Crypto Tier 1
    "BTC/USD", "ETH/USD",
    # Defense
    "RTX", "LMT", "NOC", "GD", "BA",
    "KTOS", "PLTR", "AXON", "LDOS", "SAIC", "CACI",
    "ITA", "XAR", "DFEN",
    "BAESY", "EADSY",
    # Energy
    "XOM", "CVX",
    # Leveraged 3x
    "TQQQ", "SQQQ", "SPXL", "SPXS", "UPRO", "SPXU",
    "SOXL", "SOXS", "FAS", "FAZ", "TNA", "TZA",
    # High-beta singles
    "COIN", "MSTR", "ARM", "SMCI",
    # v3.0 (2026-05-12) Aggressive Momentum + Event Switch expansion
    "AMD", "AVGO", "SMH",                # ai_nasdaq_semis bucket additions
    "USO", "OXY",                          # inflation_energy bucket additions
    "TLT",                                 # hedge_bonds bucket
    # v2.4 crypto predator Tier 2 (9 mid-cap alts)
    "SOL/USD", "AVAX/USD", "LINK/USD", "DOT/USD", "MATIC/USD",
    "LTC/USD", "BCH/USD", "UNI/USD", "AAVE/USD",
}


def _refresh_whitelist_from_config() -> None:
    """
    Augment _WHITELIST with any tickers from config/watchlists.json that
    aren't already in the hardcoded base. Single source of truth =
    watchlists.json; hardcoded set above is a fallback for environments
    where the config file is unavailable (tests / sandboxed runs).

    Idempotent — safe to call multiple times.
    """
    try:
        import os as _os, sys as _sys
        _shared_dir = _os.path.dirname(_os.path.abspath(__file__))
        if _shared_dir not in _sys.path:
            _sys.path.insert(0, _shared_dir)
        from profile import load_watchlists
        wls = load_watchlists()
        for bucket_name, cfg in wls.items():
            if not isinstance(cfg, dict):
                continue
            for t in (cfg.get("tickers") or []):
                _WHITELIST.add(t)
    except Exception:
        # Profile loader unavailable — fall back to hardcoded set above.
        pass


# Augment on import so all callers see the unified universe.
_refresh_whitelist_from_config()


# ─── Thresholds (must match docs/STRATEGY.md) ─────────────────────────────────

MAX_PER_TRADE_PCT       = 20.0   # size_usd as % of equity
MAX_PER_TICKER_PCT      = 40.0   # combined ticker exposure %
MIN_RR_RATIO            = 1.2    # take_profit / stop_loss distance
WARN_PER_TRADE_PCT      = 15.0
WARN_PER_TICKER_PCT     = 25.0
WARN_RR_UPPER           = 1.5

USE_OFFICER = os.environ.get("USE_RISK_OFFICER", "true").lower() == "true"


def _is_options_contract(symbol: str) -> bool:
    """Heuristic: OCC option symbol is 6+ chars with embedded date+CP digits."""
    return len(symbol) > 7 and any(ch.isdigit() for ch in symbol)


def _on_whitelist(symbol: str) -> bool:
    """Whitelist check. Options contracts are allowed if their underlying is."""
    if symbol in _WHITELIST:
        return True
    if _is_options_contract(symbol):
        # Heuristic: leading alpha chars before first digit = underlying root
        underlying = ""
        for ch in symbol:
            if ch.isalpha():
                underlying += ch
            else:
                break
        return underlying in _WHITELIST
    return False


def _rr_ratio(entry: float, sl: float, tp: float | None) -> float | None:
    """Compute reward:risk. Returns None if SL or TP missing / on wrong side."""
    if entry <= 0 or sl <= 0:
        return None
    sl_dist = abs(entry - sl)
    if sl_dist <= 0:
        return None
    if tp is None or tp <= 0:
        # No TP → R:R undefined. Treat as soft (don't reject just because
        # the strategy uses trailing exit). Caller can decide.
        return None
    tp_dist = abs(tp - entry)
    return tp_dist / sl_dist


# ─── Public API ───────────────────────────────────────────────────────────────

def evaluate_trade(proposal: dict[str, Any]) -> dict[str, Any]:
    """
    Validate `proposal` (entry-monitor sized) before order placement.

    Proposal shape (mirrors risk-officer.md):
      {
        "symbol":      "AAPL",
        "action":      "BUY" | "SELL_SHORT" | "BUY_TO_OPEN_CALL" | ...,
        "size_usd":    10000,
        "entry_price": 175.25,
        "stop_loss":   170.00,
        "take_profit": 180.00,
        "strategy":    "aggressive-momentum",
      }

    Returns:
      {
        "decision":      "APPROVE" | "REJECT",
        "checks_passed": [...],
        "checks_failed": [...],
        "warnings":      [...],
        "rationale":     "one-sentence explanation",
      }
    """
    if not USE_OFFICER:
        return {
            "decision":      "APPROVE",
            "checks_passed": [],
            "checks_failed": [],
            "warnings":      ["risk-officer disabled via USE_RISK_OFFICER=false"],
            "rationale":     "officer bypassed — proposal accepted as-is",
        }

    passed: list[str] = []
    failed: list[str] = []
    warnings: list[str] = []

    symbol      = (proposal.get("symbol") or "").strip().upper()
    size_usd    = float(proposal.get("size_usd") or 0)
    entry       = float(proposal.get("entry_price") or 0)
    sl          = float(proposal.get("stop_loss") or 0)
    tp          = proposal.get("take_profit")
    if tp is not None:
        try:
            tp = float(tp)
        except (TypeError, ValueError):
            tp = None

    # ── HARD: whitelist ──────────────────────────────────────────────────────
    if not symbol:
        failed.append("missing symbol")
    elif not _on_whitelist(symbol):
        failed.append(f"ticker '{symbol}' not on whitelist")
    else:
        passed.append("whitelist")

    # ── HARD: stop_loss exists ───────────────────────────────────────────────
    if sl <= 0:
        failed.append("stop_loss missing or non-positive")
    else:
        passed.append("stop_loss")

    # ── HARD: R:R ≥ 1.2 (only when TP provided) ──────────────────────────────
    rr = _rr_ratio(entry, sl, tp)
    if rr is not None:
        if rr < MIN_RR_RATIO:
            failed.append(f"R:R {rr:.2f} < {MIN_RR_RATIO}")
        else:
            passed.append(f"rr={rr:.2f}")
            if rr <= WARN_RR_UPPER:
                warnings.append(f"R:R {rr:.2f} is mid-range (warn-zone {MIN_RR_RATIO}-{WARN_RR_UPPER})")
    elif tp is None:
        # No TP — likely trailing exit strategy. Add as warning, not fail.
        warnings.append("no take_profit (trailing exit assumed)")

    # ── HARD: account-relative checks (need equity) ──────────────────────────
    # v3.10 (2026-05-27) — intraday-first policy fix per architectural directive
    # 3: "Wyjątek w risk officer / portfolio risk nie może bezrefleksyjnie
    # przepuszczać orderu. Dla krytycznych danych: BLOCK lub DEFER."
    # Account data is CRITICAL — without it we cannot enforce per-trade /
    # per-ticker / drawdown / buying-power checks. Previous behavior was
    # warn + fail-open which allowed orders to slip through during Alpaca
    # outages. New behavior: DEFER (REJECT with intraday verdict=DEFER).
    # Next cron will retry; emergency exits still proceed (they bypass
    # risk_officer entirely via emergency_close path).
    account = get_account_status()
    if account is None:
        # Critical data missing — DEFER, not fail-open. Caller (alpaca_orders)
        # treats this as transient and retries on next cron. The verdict
        # field maps to RiskVerdict.DEFER for unified taxonomy.
        return {
            "decision":      "REJECT",
            "verdict":       "DEFER",
            "checks_passed": passed,
            "checks_failed": ["account-data-unavailable (Alpaca outage) — DEFER, not fail-open"],
            "warnings":      warnings,
            "rationale":     "DEFER — Alpaca account fetch failed; retry next cron (v3.10 intraday-first policy)",
            "retry_after_s": 60,
        }
    if True:  # preserve indent of existing block
        equity = float(account.get("equity") or 0)
        if equity > 0:
            # Per-trade cap
            pct = (size_usd / equity) * 100 if size_usd > 0 else 0
            if pct > MAX_PER_TRADE_PCT:
                failed.append(f"size_usd {pct:.1f}% > {MAX_PER_TRADE_PCT}% equity")
            else:
                passed.append(f"per_trade={pct:.1f}%")
                if pct > WARN_PER_TRADE_PCT:
                    warnings.append(f"size_usd {pct:.1f}% > {WARN_PER_TRADE_PCT}% (large position)")

            # Per-ticker concentration (existing position + this trade)
            if size_usd > 0:
                ok, combined = concentration_ok(symbol, size_usd, equity)
                if not ok:
                    failed.append(
                        f"per-ticker {combined:.1f}% > {MAX_PER_TICKER_PCT}% post-trade"
                    )
                else:
                    passed.append(f"per_ticker={combined:.1f}%")
                    if combined > WARN_PER_TICKER_PCT:
                        warnings.append(
                            f"per-ticker {combined:.1f}% > {WARN_PER_TICKER_PCT}% (concentration risk)"
                        )

        # Drawdown circuit-breaker
        status, reason = daily_drawdown_guard(account)
        if status == "HALT":
            failed.append(f"daily-drawdown HALT: {reason}")
        else:
            passed.append("daily_drawdown_ok")

        # ── HARD: buying-power / PDT guard (NEW 2026-05-14) ──────────────
        # Even though guarantee covers daily_drawdown, the account can be
        # silently maxed out (initial_margin > equity → buying_power=0)
        # without firing drawdown. In that state, every new BUY/SHORT
        # order will be rejected by Alpaca with "insufficient buying
        # power" — but the monitor will keep trying every 5 min and
        # spam-block the same signal repeatedly.
        # Reject upfront when:
        #   buying_power < size_usd
        # OR account is in PDT day-trade lockout (daytrade_count >= 3 on
        # PDT-flagged account → Day Trading Margin Call). Alpaca returns
        # buying_power=0 in that state too.
        try:
            bp = float(account.get("buying_power") or 0)
            dt_count = int(account.get("daytrade_count") or 0)
            is_pdt = bool(account.get("pattern_day_trader"))
            if size_usd > 0 and bp < size_usd:
                failed.append(
                    f"buying_power ${bp:,.0f} < size_usd ${size_usd:,.0f} "
                    f"(account leveraged out — close existing positions to free BP)"
                )
            elif is_pdt and dt_count >= 3:
                warnings.append(
                    f"PDT day-trade count {dt_count} ≥ 3 — next intraday "
                    f"close+open of same symbol may trigger DTMC lockout"
                )
            else:
                passed.append(f"buying_power_ok (bp=${bp:,.0f}, dt={dt_count})")
        except (TypeError, ValueError):
            warnings.append("buying_power_check_skipped (malformed account data)")

    # ── HARD: VIX guard ──────────────────────────────────────────────────────
    vix_status, _ = vix_guard()
    if vix_status == "HALT":
        failed.append("VIX > 60 (catastrophic-only HALT)")
    else:
        passed.append("vix_ok")

    # ── v3.12.0 (2026-05-30) — SAFE_MODE gate ────────────────────────────────
    # safe_mode is RUNTIME-OPERATIONAL (different from defensive_mode which
    # is RISK-DRIVEN). Triggers: account fetch outage, audit JSONL gap,
    # stale data, confidence module broken, operator-forced. BLOCKS new
    # entries; emergency closes bypass via separate path.
    try:
        from safe_mode import gate_new_entry as _sm_gate  # type: ignore
        sm_allowed, sm_reason = _sm_gate()
        if not sm_allowed:
            failed.append(f"safe_mode: {sm_reason}")
        else:
            passed.append("safe_mode_ok")
    except Exception as e:
        # Fail-soft: missing module → assume safe_mode inactive
        warnings.append(f"safe_mode_check_skipped ({type(e).__name__})")

    # ── v3.12.0 (2026-05-30) — CONFIDENCE gate (optional) ────────────────────
    # If caller passes `confidence_inputs` in the proposal dict, compute the
    # 5-component score and block at threshold. Backward-compatible: if no
    # inputs provided, skip with a warning (no change in behavior for
    # existing callers that don't pass confidence inputs yet).
    conf_inputs = proposal.get("confidence_inputs")
    if isinstance(conf_inputs, dict) and conf_inputs:
        # v3.15.0 — honor block_recommended from feedback-driven inputs
        # BEFORE compute_confidence (cheaper, no maths needed). Reasons:
        # liquidity_sweep BLOCK, source-tier ineligibility, etc.
        meta = conf_inputs.get("_v3150_meta", {}) or {}
        if meta.get("block_recommended"):
            reasons = meta.get("block_reasons", []) or ["v3.15.0_block_recommended"]
            failed.append("v3.15.0_block: " + ",".join(str(r) for r in reasons))
        # Strip meta before passing to compute_confidence (it would be an
        # unknown kwarg).
        cleaned_inputs = {k: v for k, v in conf_inputs.items()
                          if not str(k).startswith("_v3150")}
        try:
            from confidence import compute_confidence  # type: ignore
            report = compute_confidence(**cleaned_inputs)
            if report.decision == "BLOCK":
                failed.append(
                    f"confidence={report.total:.3f} < threshold "
                    f"(weakest={min(report.components, key=report.components.get)})"
                )
            elif report.decision == "ALERT_ONLY":
                warnings.append(
                    f"confidence={report.total:.3f} ALERT_ONLY "
                    f"(allow≥{report.threshold:.2f}) — log only, do not auto-execute"
                )
            else:
                passed.append(f"confidence_ok={report.total:.3f}")
            # Surface report for downstream audit (set on a dict the
            # caller passes — proposal mutated for traceability).
            proposal["_confidence_report"] = report.to_dict()
            if meta:
                proposal["_v3150_meta"] = meta
        except Exception as e:
            warnings.append(f"confidence_check_skipped ({type(e).__name__}: {e})")
    else:
        warnings.append("confidence_inputs not provided — gate skipped (legacy caller)")

    # ── Decision ─────────────────────────────────────────────────────────────
    # v3.10: added `verdict` field for unified RiskVerdict taxonomy. Legacy
    # `decision` (APPROVE/REJECT) preserved for backward compat. New callers
    # should prefer `verdict` which maps to risk_classification.RiskVerdict.
    if failed:
        # Classify rejection: account_blocked / paper_only / off_whitelist
        # are BLOCK (hard); buying_power < size is BLOCK (cannot proceed);
        # drawdown HALT is BLOCK; everything else REJECT → BLOCK (no risk
        # check failure permits trading).
        return {
            "decision":      "REJECT",
            "verdict":       "BLOCK",
            "checks_passed": passed,
            "checks_failed": failed,
            "warnings":      warnings,
            "rationale":     f"BLOCK — {failed[0]}",
        }

    return {
        "decision":      "APPROVE",
        "verdict":       "ALLOW",
        "checks_passed": passed,
        "checks_failed": [],
        "warnings":      warnings,
        "rationale":     (
            f"ALLOW ({len(passed)} checks; {len(warnings)} warnings)"
            if warnings else f"ALLOW ({len(passed)} checks)"
        ),
    }
