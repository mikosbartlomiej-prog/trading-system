"""v3.17.0 (2026-06-04) — Feedback modules wiring helper.

Task 5: Wire v3.15 feedback modules in production flow.

WHY
---
v3.15.0/v3.16.0 added four powerful feedback-driven modules
(instrument_profile, liquidity_sweep_guard, lead_lag_analyzer,
pre_open_behavior). They are tested in isolation but DORMANT in
production: 0 wirings in *-monitor/ files. They contribute to
`confidence_builder.build_confidence_inputs` only when the caller
explicitly populates the kwargs.

This helper centralises the "build context for confidence" step.
Each monitor calls one function and forwards the result as kwargs.
Reduces boilerplate, single place to extend, single place to audit.

CONTRACT
--------
- NEVER raises.
- NEVER emits a trade.
- NEVER mutates monitor state.
- Fail-soft: any module unavailable → key omitted (downstream handles None).
- Audit fail-soft: emission errors are swallowed.

OUTPUT
------
Returns dict with optional keys:
  - instrument_profile:    InstrumentProfile | None
  - liquidity_sweep_result: SweepCheckResult | None
  - lead_lag_result:       LeadLagResult     | None
  - pre_open_analysis:     PreOpenAnalysis   | None

Caller pattern (in monitor):

    from feedback_modules_helper import build_feedback_confidence_context

    ctx = build_feedback_confidence_context(
        symbol=ticker,
        bars=bars,
        index_closes=spy_closes,
    )
    signal["confidence_inputs"] = build_confidence_inputs(
        strategy="momentum-long",
        primary_score=score,
        regime=regime,
        bars=bars,
        **ctx,
    )

The keys in `ctx` are pass-through to `confidence_builder` — same
contract preserved.

AUDIT
-----
Each module evaluation emits a JSONL event via shared/audit.py with
`kind="feedback_module"`. Audit emission is fail-soft.

Event kinds:
  - EVT_PROFILE_BUILT
  - EVT_LIQUIDITY_CHECK
  - EVT_LEAD_LAG_CHECK
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Sequence

# Audit event kinds (constants for greppability / consistency).
EVT_PROFILE_BUILT   = "FEEDBACK_PROFILE_BUILT"
EVT_LIQUIDITY_CHECK = "FEEDBACK_LIQUIDITY_CHECK"
EVT_LEAD_LAG_CHECK  = "FEEDBACK_LEAD_LAG_CHECK"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_audit(payload: dict) -> None:
    """Emit a JSONL audit event (kind=feedback_module). Never raises."""
    try:
        try:
            from audit import write_audit_event
        except ImportError:
            from shared.audit import write_audit_event  # type: ignore
        # Use kind="trading" — the helper accepts only trading/code in its
        # current signature. Trading dir is the natural place for per-decision
        # context. Caller distinguishes via the explicit `kind_label`
        # field inside the payload.
        write_audit_event(payload, kind="trading")
    except Exception:
        # Never propagate audit errors into the trading path.
        pass


def _try_import_instrument_profile():
    try:
        from instrument_profile import profile_symbol, InstrumentProfile  # noqa
        return profile_symbol
    except ImportError:
        try:
            from shared.instrument_profile import profile_symbol  # type: ignore
            return profile_symbol
        except ImportError:
            return None


def _try_import_liquidity_sweep():
    try:
        from liquidity_sweep_guard import evaluate_sweep_risk
        return evaluate_sweep_risk
    except ImportError:
        try:
            from shared.liquidity_sweep_guard import evaluate_sweep_risk  # type: ignore
            return evaluate_sweep_risk
        except ImportError:
            return None


def _try_import_lead_lag():
    try:
        from lead_lag_analyzer import analyze_lead_lag
        return analyze_lead_lag
    except ImportError:
        try:
            from shared.lead_lag_analyzer import analyze_lead_lag  # type: ignore
            return analyze_lead_lag
        except ImportError:
            return None


def _extract_series(bars: dict | None, key: str) -> list[float] | None:
    if not bars:
        return None
    arr = bars.get(key)
    if not arr:
        return None
    try:
        return [float(x) for x in arr]
    except Exception:
        return None


def build_feedback_confidence_context(*,
                                       symbol: str,
                                       bars: dict | None = None,
                                       index_closes: Sequence[float] | None = None,
                                       historical_volume: float | None = None,
                                       quote_spread_bps: float | None = None,
                                       pre_open_analysis: Any = None,
                                       ) -> dict:
    """Build feedback-driven kwargs for confidence_builder.build_confidence_inputs.

    Args:
        symbol:                 Ticker we are scoring confidence for.
        bars:                   Daily bars dict from market_data.get_daily_bars
                                shape: {open:[], high:[], low:[], close:[],
                                        volume:[], time:[]}.
        index_closes:           SPY/QQQ daily closes for lead-lag analysis.
                                If None or len < MIN_BARS_FOR_CORR, lead_lag
                                step is skipped (key omitted).
        historical_volume:      Optional explicit avg volume — currently used
                                only for caller convenience / future hooks.
        quote_spread_bps:       Optional quote spread in basis points for
                                low-liquidity component of sweep guard.
        pre_open_analysis:      Optional pre-built PreOpenAnalysis dataclass
                                (caller opts into this — helper does not
                                fetch pre-market data itself; deferred wiring
                                per task spec).

    Returns:
        dict with 0..N of these keys:
            instrument_profile
            liquidity_sweep_result
            lead_lag_result
            pre_open_analysis

    Each module failure → key omitted (downstream confidence_builder treats
    missing as neutral).

    NEVER raises.
    """
    ctx: dict[str, Any] = {}

    sym_safe = (symbol or "").strip().upper() or "UNKNOWN"

    # ── 1) Instrument profile ───────────────────────────────────────────────
    profile_symbol_fn = _try_import_instrument_profile()
    profile_obj = None
    if profile_symbol_fn is not None:
        try:
            profile_obj = profile_symbol_fn(sym_safe)
        except Exception:
            profile_obj = None
    if profile_obj is not None:
        ctx["instrument_profile"] = profile_obj
        try:
            quality = float(getattr(profile_obj, "quality", 0.0) or 0.0)
            insufficient = bool(getattr(profile_obj, "insufficient_data", False))
            bars_count = int(getattr(profile_obj, "bars_count", 0) or 0)
            _safe_audit({
                "type": EVT_PROFILE_BUILT,
                "kind_label": "feedback_module",
                "symbol": sym_safe,
                "quality": quality,
                "insufficient_data": insufficient,
                "bars_count": bars_count,
                "at": _now_iso(),
            })
        except Exception:
            pass

    # ── 2) Liquidity sweep check ────────────────────────────────────────────
    sweep_fn = _try_import_liquidity_sweep()
    if sweep_fn is not None and bars:
        opens   = _extract_series(bars, "open")
        highs   = _extract_series(bars, "high")
        lows    = _extract_series(bars, "low")
        closes  = _extract_series(bars, "close")
        volumes = _extract_series(bars, "volume")
        # Only evaluate when we have at least the OHLC quartet.
        if (opens is not None and highs is not None and
                lows is not None and closes is not None and
                len(closes) >= 2):
            try:
                sweep_result = sweep_fn(
                    opens=opens, highs=highs, lows=lows, closes=closes,
                    volumes=volumes,
                    quote_spread_bps=quote_spread_bps,
                    profile=profile_obj,
                )
                ctx["liquidity_sweep_result"] = sweep_result
                try:
                    _safe_audit({
                        "type": EVT_LIQUIDITY_CHECK,
                        "kind_label": "feedback_module",
                        "symbol": sym_safe,
                        "verdict": getattr(sweep_result, "verdict", ""),
                        "signal_count": int(getattr(sweep_result, "signal_count", 0) or 0),
                        "triggered_signals": list(
                            getattr(sweep_result, "triggered_signals", ()) or ()),
                        "at": _now_iso(),
                    })
                except Exception:
                    pass
            except Exception:
                pass

    # ── 3) Lead-lag analysis ────────────────────────────────────────────────
    lead_lag_fn = _try_import_lead_lag()
    if lead_lag_fn is not None and bars and index_closes is not None:
        sym_closes = _extract_series(bars, "close")
        try:
            idx_list = [float(x) for x in index_closes]
        except Exception:
            idx_list = None
        if (sym_closes is not None and idx_list is not None
                and len(sym_closes) >= 5 and len(idx_list) >= 5):
            try:
                lead_lag_result = lead_lag_fn(
                    symbol_closes=sym_closes,
                    index_closes=idx_list,
                )
                ctx["lead_lag_result"] = lead_lag_result
                try:
                    _safe_audit({
                        "type": EVT_LEAD_LAG_CHECK,
                        "kind_label": "feedback_module",
                        "symbol": sym_safe,
                        "verdict": getattr(lead_lag_result, "verdict", ""),
                        "contemporaneous_corr": float(
                            getattr(lead_lag_result, "contemporaneous_corr", 0.0)
                            or 0.0),
                        "best_lag": int(getattr(lead_lag_result, "best_lag", 0) or 0),
                        "at": _now_iso(),
                    })
                except Exception:
                    pass
            except Exception:
                pass

    # ── 4) Pre-open analysis pass-through ───────────────────────────────────
    # Spec: SKIP unless explicit pre_market_bars passed (operator decision:
    # deferred wiring). We honor an externally-built analysis when supplied.
    if pre_open_analysis is not None:
        ctx["pre_open_analysis"] = pre_open_analysis

    return ctx


__all__ = [
    "build_feedback_confidence_context",
    "EVT_PROFILE_BUILT",
    "EVT_LIQUIDITY_CHECK",
    "EVT_LEAD_LAG_CHECK",
]
