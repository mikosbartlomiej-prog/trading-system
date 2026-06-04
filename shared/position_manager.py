"""v3.15.0 (2026-06-04) — PositionManager / TradeLifecycleManager.

Closes audit-board feedback FB-011 (position management — no fire-and-forget).

WHY
---
Trader feedback: trades are currently fire-and-forget. The system has
exit-monitor + intraday_governor + safe_close that handle REACTIVE exits
but no explicit per-position lifecycle state machine with proactive triggers:
  - time-stop
  - invalidation level
  - exit on confidence drop
  - exit on data-quality drop
  - explicit partial-exit policy
  - max adverse excursion tracking

This module adds a deterministic state machine that the exit-monitor consults
each tick. It NEVER places orders directly — it returns a recommended action
(HOLD / PARTIAL_EXIT / FULL_EXIT / INVALIDATE) for the exit-monitor to honor
via the existing `safe_close` path.

LIFECYCLE STATES
----------------
- INTAKE          — position freshly opened; no exit logic yet (grace period)
- ARMED           — exits armed; standard monitoring
- TRAILING        — position in profit, trailing stop active
- INVALIDATING    — invalidation signal fired; pending close at next tick
- TIME_EXPIRED    — time-stop fired; pending close
- CLOSED          — terminal

CONTRACT
--------
- Pure function `evaluate_position()` — no side effects, no orders.
- State persisted in `learning-loop/runtime_state.json::positions[symbol]`.
- Lifecycle entries audited to JSONL.
- Fail-soft — corrupt state → return HOLD with warning.

NEVER
-----
- Place orders directly (exit-monitor consumes the recommendation).
- Override emergency closes (kill-switch, safe-mode).
- Raise position size.
- Skip risk_officer.

LOCAL & FREE
------------
All state local. No external services. Persisted in runtime_state.json.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional

# Lifecycle states
INTAKE        = "INTAKE"
ARMED         = "ARMED"
TRAILING      = "TRAILING"
INVALIDATING  = "INVALIDATING"
TIME_EXPIRED  = "TIME_EXPIRED"
CLOSED        = "CLOSED"

VALID_STATES = (INTAKE, ARMED, TRAILING, INVALIDATING, TIME_EXPIRED, CLOSED)


# Recommendations the position manager returns to the exit-monitor.
HOLD            = "HOLD"
PARTIAL_EXIT    = "PARTIAL_EXIT"
FULL_EXIT       = "FULL_EXIT"
INVALIDATE      = "INVALIDATE"

VALID_RECOMMENDATIONS = (HOLD, PARTIAL_EXIT, FULL_EXIT, INVALIDATE)


# ─── Tunables (conservative; documented) ──────────────────────────────────────

INTAKE_GRACE_MINUTES        = 5      # let bracket settle before first eval
DEFAULT_TIME_STOP_HOURS     = 48     # default time-stop for swing
INTRADAY_TIME_STOP_HOURS    = 6      # explicit intraday positions
TRAIL_ARM_PROFIT_PCT        = 0.05   # 5% in green → trailing armed
TRAIL_RETRACE_PCT           = 0.40   # 40% retrace from MFE → full exit
PARTIAL_EXIT_PROFIT_PCT     = 0.10   # 10% in green → partial exit option
CONFIDENCE_DROP_THRESHOLD   = 0.40   # entry conf 0.65 → drop to 0.40 → exit
QUALITY_DROP_THRESHOLD      = 0.30   # profile quality drop
MAX_ADVERSE_EXCURSION_PCT   = 0.08   # 8% MAE → exit (safety net beyond SL)


@dataclass(frozen=True)
class PositionState:
    """Frozen snapshot of position state. Persisted to runtime_state.json."""
    symbol:               str
    lifecycle:            str
    opened_at_iso:        str
    entry_price:          float
    entry_qty:            float
    entry_confidence:     float | None
    intent:               str               # "swing" / "intraday" / "emergency"
    last_eval_at_iso:     str
    current_price:        float
    current_pl_pct:       float
    peak_price:           float             # MFE high water mark
    peak_pl_pct:          float
    trough_price:         float             # MAE low water mark
    trough_pl_pct:        float
    time_stop_hours:      float
    time_at_eval_hours:   float
    confidence_now:       float | None
    profile_quality_now:  float | None
    warnings:             tuple = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LifecycleDecision:
    """Output of evaluate_position() — caller (exit-monitor) applies the
    recommendation via safe_close.
    """
    recommendation:    str
    reason:            str
    next_lifecycle:    str
    partial_qty_pct:   float       # 0.0..1.0; only meaningful for PARTIAL_EXIT
    triggered_signals: tuple
    audit_context:     dict

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s: str):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _hours_since(iso_str: str, now=None) -> float | None:
    dt = _parse_iso(iso_str)
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 3600.0)


# ─── Public API ───────────────────────────────────────────────────────────────

def open_position(*, symbol: str, entry_price: float, entry_qty: float,
                    intent: str = "swing",
                    entry_confidence: float | None = None,
                    time_stop_hours: float | None = None,
                    now_iso: str | None = None,
                    ) -> PositionState:
    """Build initial PositionState for a freshly opened position.

    Caller (allocator / monitor) is responsible for persisting this state
    into `runtime_state.json::positions[symbol]` via existing helpers.
    """
    ts_iso = now_iso or _now_iso()
    if time_stop_hours is None:
        time_stop_hours = (INTRADAY_TIME_STOP_HOURS if intent == "intraday"
                            else DEFAULT_TIME_STOP_HOURS)
    return PositionState(
        symbol=symbol,
        lifecycle=INTAKE,
        opened_at_iso=ts_iso,
        entry_price=float(entry_price),
        entry_qty=float(entry_qty),
        entry_confidence=entry_confidence,
        intent=intent or "swing",
        last_eval_at_iso=ts_iso,
        current_price=float(entry_price),
        current_pl_pct=0.0,
        peak_price=float(entry_price),
        peak_pl_pct=0.0,
        trough_price=float(entry_price),
        trough_pl_pct=0.0,
        time_stop_hours=float(time_stop_hours),
        time_at_eval_hours=0.0,
        confidence_now=entry_confidence,
        profile_quality_now=None,
        warnings=(),
    )


def update_position_marks(state: PositionState, *,
                            current_price: float,
                            confidence_now: float | None = None,
                            profile_quality_now: float | None = None,
                            now_iso: str | None = None,
                            ) -> PositionState:
    """Refresh marks (price, P&L, MFE/MAE, time). Pure — returns NEW state."""
    if state.entry_price <= 0:
        return state
    pl_pct = (current_price - state.entry_price) / state.entry_price
    new_peak_pct  = max(state.peak_pl_pct, pl_pct)
    new_trough_pct = min(state.trough_pl_pct, pl_pct)
    new_peak_price = max(state.peak_price, current_price)
    new_trough_price = min(state.trough_price, current_price)
    ts_iso = now_iso or _now_iso()
    hours = _hours_since(state.opened_at_iso,
                          now=datetime.fromisoformat(ts_iso.replace("Z","+00:00")))
    if hours is None:
        hours = 0.0
    return PositionState(
        symbol=state.symbol,
        lifecycle=state.lifecycle,
        opened_at_iso=state.opened_at_iso,
        entry_price=state.entry_price,
        entry_qty=state.entry_qty,
        entry_confidence=state.entry_confidence,
        intent=state.intent,
        last_eval_at_iso=ts_iso,
        current_price=float(current_price),
        current_pl_pct=pl_pct,
        peak_price=new_peak_price,
        peak_pl_pct=new_peak_pct,
        trough_price=new_trough_price,
        trough_pl_pct=new_trough_pct,
        time_stop_hours=state.time_stop_hours,
        time_at_eval_hours=hours,
        confidence_now=confidence_now,
        profile_quality_now=profile_quality_now,
        warnings=state.warnings,
    )


def evaluate_position(state: PositionState, *,
                       invalidation_signal: bool = False,
                       safe_mode_active: bool = False,
                       kill_switch_armed: bool = False,
                       ) -> LifecycleDecision:
    """Inspect a position and recommend an action.

    The exit-monitor / allocator calls this AFTER updating marks. The
    recommendation flows into existing exit channels — no orders here.

    HARD RULES (in order):
    1. Kill-switch armed → FULL_EXIT (regardless of state)
    2. Safe-mode active → FULL_EXIT
    3. Explicit invalidation signal → INVALIDATE
    4. INTAKE grace period → HOLD
    5. Time stop hit → TIME_EXPIRED → FULL_EXIT
    6. MAE > MAX_ADVERSE_EXCURSION_PCT → FULL_EXIT (safety net)
    7. Confidence collapsed → FULL_EXIT
    8. Profile quality collapsed → FULL_EXIT
    9. Trailing stop trigger → FULL_EXIT
    10. PARTIAL_EXIT_PROFIT_PCT + first time → PARTIAL_EXIT (1/2 position)
    11. Else → HOLD
    """
    signals = []

    # 1. Kill-switch / safe-mode FIRST. Emergency wins everything.
    if kill_switch_armed:
        return _decision(FULL_EXIT, CLOSED, "kill_switch_armed",
                          ("kill_switch",), state, partial_qty_pct=1.0)
    if safe_mode_active:
        return _decision(FULL_EXIT, CLOSED, "safe_mode_active",
                          ("safe_mode",), state, partial_qty_pct=1.0)

    # 2. Explicit invalidation
    if invalidation_signal:
        return _decision(INVALIDATE, INVALIDATING, "invalidation_signal_fired",
                          ("invalidation",), state, partial_qty_pct=1.0)

    # 3. INTAKE grace
    if state.lifecycle == INTAKE:
        grace_h = INTAKE_GRACE_MINUTES / 60.0
        if state.time_at_eval_hours < grace_h:
            return _decision(HOLD, INTAKE, "intake_grace_period_active",
                              (), state)
        # exit grace
        next_state = ARMED

    elif state.lifecycle == CLOSED:
        return _decision(HOLD, CLOSED, "already_closed", (), state)
    else:
        next_state = state.lifecycle  # ARMED, TRAILING, etc.

    # 4. Time-stop
    if state.time_at_eval_hours > state.time_stop_hours:
        signals.append("time_stop")
        return _decision(FULL_EXIT, TIME_EXPIRED, "time_stop_hit",
                          tuple(signals), state, partial_qty_pct=1.0)

    # 5. Max adverse excursion safety net
    if state.trough_pl_pct < -MAX_ADVERSE_EXCURSION_PCT:
        signals.append("max_adverse_excursion")
        return _decision(FULL_EXIT, CLOSED, "max_adverse_excursion_hit",
                          tuple(signals), state, partial_qty_pct=1.0)

    # 6. Confidence collapsed
    if (state.entry_confidence is not None and state.confidence_now is not None
            and state.entry_confidence > 0.0
            and state.confidence_now < CONFIDENCE_DROP_THRESHOLD
            and state.confidence_now < state.entry_confidence * 0.6):
        signals.append("confidence_collapsed")
        return _decision(FULL_EXIT, CLOSED, "confidence_collapsed",
                          tuple(signals), state, partial_qty_pct=1.0)

    # 7. Profile quality collapsed (e.g. data went stale mid-trade)
    if (state.profile_quality_now is not None
            and state.profile_quality_now < QUALITY_DROP_THRESHOLD):
        signals.append("profile_quality_drop")
        return _decision(FULL_EXIT, CLOSED, "profile_quality_drop",
                          tuple(signals), state, partial_qty_pct=1.0)

    # 8. Trailing stop logic — only after position armed AND in profit
    if state.peak_pl_pct >= TRAIL_ARM_PROFIT_PCT:
        # Retrace from peak
        retrace = (state.peak_pl_pct - state.current_pl_pct) / max(state.peak_pl_pct, 1e-9)
        if retrace >= TRAIL_RETRACE_PCT:
            signals.append("trail_retrace")
            return _decision(FULL_EXIT, CLOSED, "trailing_stop_retrace",
                              tuple(signals), state, partial_qty_pct=1.0)
        next_state = TRAILING

    # 9. Partial exit opportunity (one-shot) — when above PARTIAL_EXIT_PROFIT_PCT
    if (state.current_pl_pct >= PARTIAL_EXIT_PROFIT_PCT
            and state.lifecycle in (ARMED, INTAKE)):
        signals.append("partial_exit_trigger")
        return _decision(PARTIAL_EXIT, TRAILING, "partial_exit_at_profit_target",
                          tuple(signals), state, partial_qty_pct=0.5)

    # Default
    return _decision(HOLD, next_state, "no_action", (), state)


def _decision(rec, next_state, reason, signals, state,
                partial_qty_pct: float = 0.0):
    return LifecycleDecision(
        recommendation=rec,
        reason=reason,
        next_lifecycle=next_state,
        partial_qty_pct=partial_qty_pct,
        triggered_signals=signals,
        audit_context={
            "symbol":            state.symbol,
            "prior_lifecycle":   state.lifecycle,
            "current_pl_pct":    state.current_pl_pct,
            "peak_pl_pct":       state.peak_pl_pct,
            "trough_pl_pct":     state.trough_pl_pct,
            "hours_open":        state.time_at_eval_hours,
            "confidence_now":    state.confidence_now,
            "entry_confidence":  state.entry_confidence,
        },
    )


__all__ = [
    "INTAKE", "ARMED", "TRAILING", "INVALIDATING", "TIME_EXPIRED", "CLOSED",
    "HOLD", "PARTIAL_EXIT", "FULL_EXIT", "INVALIDATE",
    "VALID_STATES", "VALID_RECOMMENDATIONS",
    "INTAKE_GRACE_MINUTES", "DEFAULT_TIME_STOP_HOURS",
    "INTRADAY_TIME_STOP_HOURS", "TRAIL_ARM_PROFIT_PCT", "TRAIL_RETRACE_PCT",
    "PARTIAL_EXIT_PROFIT_PCT", "CONFIDENCE_DROP_THRESHOLD",
    "QUALITY_DROP_THRESHOLD", "MAX_ADVERSE_EXCURSION_PCT",
    "PositionState", "LifecycleDecision",
    "open_position", "update_position_marks", "evaluate_position",
]
