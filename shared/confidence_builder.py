"""v3.14.0 (2026-06-02) — confidence_inputs builder helper for monitors.

WHY
---
The 2026-06-02 audit-board Final Arbiter flagged CONF-002 / DATA-002 /
TEST-002: confidence score architecture is sound but DORMANT in production
because no monitor passes `confidence_inputs` to risk_officer. Each monitor
has slightly different data sources (RSI, bars, regime). Without a shared
builder, wiring 11 monitors → 11 different bug surfaces.

This helper builds a `confidence_inputs` dict from common monitor-side
context (bars, regime, account_status, intraday_governor state) so each
monitor just calls one function and passes the result through the signal
dict.

CONTRACT
--------
The returned dict is shaped exactly for `shared/confidence.compute_confidence(**kwargs)`.
ALL keys are optional — `compute_confidence` handles missing data by
falling back to neutral 0.5 per component. Pass what you have, omit
what you don't.

KEY GROUPS (matching shared/confidence.py)
- data_quality:     bar_age_seconds, quote_spread_pct, bars_count
- signal_strength:  primary_score, confirmations
- regime_alignment: regime, strategy
- system_health:    components_alive, components_total, recent_errors, audit_gap_seconds
- risk_state:       intraday_pnl_pct, giveback_pct_of_peak, consecutive_losses, drawdown_pct
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional


def _bar_age_seconds(bars: list | None) -> Optional[float]:
    """Return seconds since most-recent bar's close timestamp.

    Bars from shared/market_data are dicts with 't' (ISO) or 'timestamp'.
    Returns None if we cannot determine.
    """
    if not bars:
        return None
    last = bars[-1]
    ts = last.get("t") or last.get("timestamp") or last.get("close_at")
    if not ts:
        return None
    try:
        if isinstance(ts, (int, float)):
            return max(0.0, time.time() - float(ts))
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
    except Exception:
        return None


def build_confidence_inputs(*,
                             # signal context
                             strategy: str,
                             primary_score: float | None = None,
                             confirmations: int | None = None,
                             # data context
                             bars: list | None = None,
                             bars_count: int | None = None,
                             quote_spread_pct: float | None = None,
                             # regime context
                             regime: str | None = None,
                             # account / portfolio context
                             account_status: dict | None = None,
                             governor_state: dict | None = None,
                             consecutive_losses: int | None = None,
                             ) -> dict:
    """Build a confidence_inputs dict suitable for compute_confidence.

    Fail-soft: any computation error → that key is omitted (compute_confidence
    falls back to neutral 0.5 per missing component). NEVER raises.

    Convention:
      - primary_score: monitor's own composite signal score [-1..+1] or [0..1].
        Passed as-is; confidence.score_signal_strength clamps + maps.
      - confirmations: count of independent confirmations (volume, RSI,
        regime alignment, news). Higher = stronger.
      - regime: one of {RISK_ON, RISK_OFF, INFLATION_SHOCK, NEUTRAL}.
      - strategy: strategy name (used for regime-alignment lookup).
    """
    out: dict = {"strategy": strategy}

    # signal_strength
    if primary_score is not None:
        try:
            out["primary_score"] = float(primary_score)
        except Exception:
            pass
    if confirmations is not None:
        try:
            out["confirmations"] = int(confirmations)
        except Exception:
            pass

    # data_quality
    try:
        bar_age = _bar_age_seconds(bars)
        if bar_age is not None:
            out["bar_age_seconds"] = bar_age
    except Exception:
        pass
    try:
        cnt = bars_count if bars_count is not None else (len(bars) if bars else None)
        if cnt is not None:
            out["bars_count"] = int(cnt)
    except Exception:
        pass
    if quote_spread_pct is not None:
        try:
            out["quote_spread_pct"] = float(quote_spread_pct)
        except Exception:
            pass

    # regime_alignment
    if regime:
        out["regime"] = str(regime)

    # system_health — read from heartbeat module
    try:
        from heartbeat import health_snapshot
        snap = health_snapshot()
        out["components_alive"] = snap.get("alive")
        out["components_total"] = snap.get("total")
    except Exception:
        try:
            from shared.heartbeat import health_snapshot  # type: ignore
            snap = health_snapshot()
            out["components_alive"] = snap.get("alive")
            out["components_total"] = snap.get("total")
        except Exception:
            pass

    # risk_state
    if account_status:
        try:
            out["intraday_pnl_pct"] = float(account_status.get("daily_pl_pct"))
        except Exception:
            pass
    if governor_state:
        try:
            peak = float(governor_state.get("peak_pnl_usd") or 0)
            current = float(governor_state.get("current_pnl_usd") or 0)
            if peak > 0 and current < peak:
                out["giveback_pct_of_peak"] = (peak - current) / peak * 100.0
        except Exception:
            pass
    if consecutive_losses is not None:
        try:
            out["consecutive_losses"] = int(consecutive_losses)
        except Exception:
            pass

    return out


__all__ = ["build_confidence_inputs"]
