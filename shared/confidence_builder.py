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
                             # v3.15.0 — new feedback-driven inputs
                             instrument_profile=None,
                             liquidity_sweep_result=None,
                             lead_lag_result=None,
                             source_type: str | None = None,
                             source_confirmation_present: bool = False,
                             pre_open_analysis=None,
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

    # v3.15.0 (2026-06-04) — feedback-driven inputs
    # All adjustments are CONSERVATIVE: caps at ±0.10 net, BLOCK trade
    # routed via risk_officer (this only modifies the signal_strength
    # component via primary_score adjustment).
    out["_v3150_meta"] = {}
    out, meta = _apply_v3150_adjustments(
        out,
        instrument_profile=instrument_profile,
        liquidity_sweep_result=liquidity_sweep_result,
        lead_lag_result=lead_lag_result,
        source_type=source_type,
        source_confirmation_present=source_confirmation_present,
        pre_open_analysis=pre_open_analysis,
    )
    if not meta:
        out.pop("_v3150_meta", None)
    else:
        out["_v3150_meta"] = meta

    return out


def _apply_v3150_adjustments(out: dict, *,
                              instrument_profile=None,
                              liquidity_sweep_result=None,
                              lead_lag_result=None,
                              source_type: str | None = None,
                              source_confirmation_present: bool = False,
                              pre_open_analysis=None) -> tuple[dict, dict]:
    """Apply v3.15.0 feedback-driven confidence adjustments.

    Conservative rules:
      - Each adjustment caps at ±0.05 individually.
      - NET adjustment clamps to [-0.20, +0.10].
      - BLOCK verdict (liquidity sweep BLOCK / source tier ineligibility)
        is NOT enforced here — caller's risk_officer / outer gate must
        check `_v3150_meta.block_recommended`. This function only adjusts
        the score components passed to compute_confidence.
    """
    meta: dict = {}
    adj_total = 0.0
    block_recommended = False
    block_reasons: list[str] = []

    # ── Instrument profile quality ──────────────────────────────────────────
    if instrument_profile is not None:
        try:
            quality = float(getattr(instrument_profile, "quality", 0.0) or 0.0)
            insufficient = bool(getattr(instrument_profile, "insufficient_data", False))
            meta["instrument_profile_quality"] = quality
            meta["instrument_profile_insufficient"] = insufficient
            # Low quality / insufficient data → reduce data_quality component
            # signal via penalty applied to primary_score (capped).
            if insufficient:
                adj_total -= 0.05
            elif quality < 0.5:
                adj_total -= 0.03
        except Exception:
            pass

    # ── Liquidity sweep ─────────────────────────────────────────────────────
    if liquidity_sweep_result is not None:
        try:
            verdict = getattr(liquidity_sweep_result, "verdict", "")
            meta["liquidity_sweep_verdict"] = verdict
            if verdict == "BLOCK":
                block_recommended = True
                block_reasons.append("liquidity_sweep_BLOCK")
                adj_total -= 0.10
            elif verdict == "ELEVATED_RISK":
                adj_total -= 0.05
        except Exception:
            pass

    # ── Lead-lag adjustment ─────────────────────────────────────────────────
    if lead_lag_result is not None:
        try:
            v = getattr(lead_lag_result, "verdict", "")
            meta["lead_lag_verdict"] = v
            if v == "INDEX_ALIGNED":
                adj_total += 0.03
            elif v == "DELAYED_FOLLOWER":
                adj_total += 0.02
            elif v == "INDEX_DIVERGENT":
                adj_total -= 0.05
        except Exception:
            pass

    # ── Source tier ─────────────────────────────────────────────────────────
    if source_type:
        try:
            from source_quality import (
                tier_for, confidence_ceiling_for, is_day_trade_eligible_alone,
                TIER_3, TIER_UNKNOWN,
            )
        except ImportError:
            try:
                from shared.source_quality import (  # type: ignore
                    tier_for, confidence_ceiling_for, is_day_trade_eligible_alone,
                    TIER_3, TIER_UNKNOWN,
                )
            except ImportError:
                tier_for = None
        if tier_for is not None:
            try:
                tier = tier_for(source_type)
                ceiling = confidence_ceiling_for(source_type)
                meta["source_tier"] = tier
                meta["source_ceiling"] = ceiling
                # Tier 3 / unknown cannot drive day-trade alone.
                if tier in (TIER_3, TIER_UNKNOWN) and not source_confirmation_present:
                    # Cap the contribution by lowering primary_score adj.
                    adj_total -= 0.05
                    meta["source_tier_capped"] = True
            except Exception:
                pass

    # ── Pre-open behavior ───────────────────────────────────────────────────
    if pre_open_analysis is not None:
        try:
            cadj = float(getattr(pre_open_analysis, "confidence_adjustment", 0.0) or 0.0)
            cadj = max(-0.10, min(0.05, cadj))   # clip
            adj_total += cadj
            meta["pre_open_label"] = getattr(pre_open_analysis, "label", "")
            meta["pre_open_adjustment"] = cadj
        except Exception:
            pass

    # Clamp net adjustment
    adj_total = max(-0.20, min(0.10, adj_total))

    if adj_total != 0.0:
        # We apply the adjustment to primary_score (signal_strength component),
        # because that has natural [0,1] scaling. We clip to [0,1] so we
        # never overflow.
        try:
            base = float(out.get("primary_score", 0.5))
        except Exception:
            base = 0.5
        new_score = max(0.0, min(1.0, base + adj_total))
        out["primary_score"] = new_score
        meta["primary_score_adjusted_by"] = adj_total
        meta["primary_score_after"] = new_score

    if block_recommended:
        meta["block_recommended"] = True
        meta["block_reasons"] = block_reasons

    return out, meta


__all__ = ["build_confidence_inputs"]
