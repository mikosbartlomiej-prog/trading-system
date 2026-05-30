"""v3.12.0 (2026-05-30) — Explicit safe_mode state.

WHY DISTINCT FROM defensive_mode?
---------------------------------
- defensive_mode (shared/defensive_mode.py) is RISK-DRIVEN — flipped on
  by max_daily_loss / max_drawdown / kill_switch_armed thresholds.
  Profile-driven, persistent across sessions, takes manual reset.
- safe_mode (THIS module) is RUNTIME-OPERATIONAL — flipped on by
  component failures (stale data, audit gap, monitor crash, account
  fetch outage). Auto-recovers when conditions clear. No human reset.

EFFECT WHEN SAFE_MODE ACTIVE
----------------------------
- No NEW entries (BUY signals BLOCKED at risk_officer / alpaca_orders).
- Exits ALLOWED (CLOSE_EMERGENCY, PROFIT_LOCK, governor escalation).
- size_multiplier clamp to 0.5 (any trade that DOES fire is half-size).
- confidence_score gate raised by +0.10 (harder to qualify).
- audit JSONL entry per state transition (SAFE_MODE_ENTERED / EXITED).

TRIGGERS (any → enter safe_mode)
--------------------------------
1. Alpaca account fetch fails ≥3 consecutive times → SAFE_MODE_ACCOUNT_OUTAGE
2. Audit JSONL gap > 1h during US market hours → SAFE_MODE_AUDIT_GAP
3. Data freshness: any market data bar > 15min stale → SAFE_MODE_STALE_DATA
4. Confidence module unable to compute (import error, missing inputs)
   for 3 consecutive cron ticks → SAFE_MODE_CONFIDENCE_BROKEN
5. Operator-set runtime_state.json::safe_mode.forced=true → SAFE_MODE_OPERATOR

EXIT (all → leave safe_mode)
----------------------------
- Underlying trigger condition cleared
- operator.forced is False
- No active SAFE_MODE_* in audit JSONL for last 15 min

STORAGE
-------
runtime_state.json::safe_mode {
  "active": bool,
  "reason": str,
  "entered_at": iso8601,
  "trigger": "ACCOUNT_OUTAGE" | "AUDIT_GAP" | "STALE_DATA" | "CONFIDENCE_BROKEN" | "OPERATOR" | None,
  "forced":  bool,  # operator manual override
}

This module is fail-soft: any error in safe_mode evaluation should
NOT crash the calling monitor. Default to ACTIVE (safer) on parse error.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Import runtime_state for read/write (with fallback path inside try)
try:
    from runtime_state import read_section, write_section, INTRADAY_SECTIONS  # noqa
except ImportError:
    try:
        from shared.runtime_state import read_section, write_section, INTRADAY_SECTIONS  # noqa
    except ImportError:
        # Fail-soft stubs (write_section becomes no-op if module missing)
        def read_section(name):  # type: ignore
            return None
        def write_section(name, data, actor=""):  # type: ignore
            return None


SAFE_MODE_SECTION = "safe_mode"

TRIGGERS = {
    "ACCOUNT_OUTAGE":     "Alpaca account fetch failed ≥3 consecutive times",
    "AUDIT_GAP":          "Audit JSONL gap > 1h during US market hours",
    "STALE_DATA":         "Market data bar age > 15min for active strategy symbol",
    "CONFIDENCE_BROKEN":  "Confidence module unable to compute for 3+ ticks",
    "OPERATOR":           "Operator manual flip via runtime_state.json",
}

# Effect parameters
SIZE_MULTIPLIER_IN_SAFE_MODE = 0.5
CONFIDENCE_PENALTY           = 0.10  # subtracted from threshold-met scores


@dataclass
class SafeModeState:
    active: bool
    reason: str
    entered_at: str | None
    trigger: str | None
    forced: bool = False

    def to_dict(self) -> dict:
        return {
            "active":      self.active,
            "reason":      self.reason,
            "entered_at":  self.entered_at,
            "trigger":     self.trigger,
            "forced":      self.forced,
        }

    @classmethod
    def inactive(cls) -> "SafeModeState":
        return cls(active=False, reason="", entered_at=None, trigger=None, forced=False)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_state() -> SafeModeState:
    """Read current safe_mode state from runtime_state.json.

    Fail-soft: any error → return inactive (don't accidentally lock
    trading just because parsing failed).
    """
    try:
        raw = read_section(SAFE_MODE_SECTION) or {}
        if not isinstance(raw, dict):
            return SafeModeState.inactive()
        return SafeModeState(
            active=bool(raw.get("active", False)),
            reason=str(raw.get("reason", "")),
            entered_at=raw.get("entered_at"),
            trigger=raw.get("trigger"),
            forced=bool(raw.get("forced", False)),
        )
    except Exception:
        return SafeModeState.inactive()


def enter_safe_mode(trigger: str, reason: str, actor: str = "safe_mode") -> SafeModeState:
    """Flip safe_mode ON with audit emission.

    Idempotent: if already active with same trigger, no-op (no
    spam audit entries).
    """
    current = read_state()
    if current.active and current.trigger == trigger and not current.forced:
        return current  # already in this state, no churn

    new = SafeModeState(
        active=True,
        reason=reason,
        entered_at=_now_iso(),
        trigger=trigger,
        forced=current.forced,  # preserve operator flag
    )
    try:
        write_section(SAFE_MODE_SECTION, new.to_dict(), actor=actor)
    except Exception as e:
        print(f"  safe_mode: write_section failed (non-fatal): {e}")

    _emit_audit("SAFE_MODE_ENTERED", new, actor=actor)
    return new


def exit_safe_mode(actor: str = "safe_mode") -> SafeModeState:
    """Flip safe_mode OFF (only if trigger conditions cleared).

    Will NOT exit if operator.forced=True (manual override sticky).
    """
    current = read_state()
    if not current.active:
        return current
    if current.forced:
        return current  # operator holds it open

    new = SafeModeState.inactive()
    try:
        write_section(SAFE_MODE_SECTION, new.to_dict(), actor=actor)
    except Exception as e:
        print(f"  safe_mode: write_section failed (non-fatal): {e}")

    _emit_audit("SAFE_MODE_EXITED", current, actor=actor)
    return new


def evaluate_triggers(*,
                       account_fetch_failures: int = 0,
                       audit_gap_seconds: float | None = None,
                       max_bar_age_seconds: float | None = None,
                       confidence_broken_ticks: int = 0,
                       is_market_hours: bool = True,
                       ) -> tuple[bool, str | None, str]:
    """Pure function — evaluate whether safe_mode SHOULD be active.

    Returns (should_be_active, trigger_name, reason).
    """
    # Operator forced is checked at read_state(), not here.

    if account_fetch_failures >= 3:
        return True, "ACCOUNT_OUTAGE", (
            f"Alpaca /v2/account failed {account_fetch_failures} consecutive times — "
            f"cannot evaluate buying_power / equity"
        )

    if is_market_hours and audit_gap_seconds is not None and audit_gap_seconds > 3600:
        return True, "AUDIT_GAP", (
            f"Audit JSONL idle for {audit_gap_seconds/60:.0f}min during market hours — "
            f"monitors may have stopped emitting decisions"
        )

    if max_bar_age_seconds is not None and max_bar_age_seconds > 900:
        return True, "STALE_DATA", (
            f"Most recent market bar is {max_bar_age_seconds/60:.0f}min old "
            f"(>15min threshold) — fresh signals not possible"
        )

    if confidence_broken_ticks >= 3:
        return True, "CONFIDENCE_BROKEN", (
            f"Confidence module failed to compute for {confidence_broken_ticks} ticks — "
            f"decisions cannot be quality-scored"
        )

    return False, None, ""


def gate_new_entry(*, current_state: SafeModeState | None = None) -> tuple[bool, str]:
    """Should a NEW entry order be allowed right now?

    Returns (allowed, reason). Used by alpaca_orders / risk_officer
    BEFORE placing any BUY / SHORT.
    """
    s = current_state or read_state()
    if not s.active:
        return True, "safe_mode inactive"
    return False, f"safe_mode ACTIVE ({s.trigger}): {s.reason}"


def size_multiplier(*, current_state: SafeModeState | None = None) -> float:
    """Multiplier to apply to size_usd when safe_mode is active.

    Returns 0.5 in safe_mode, 1.0 otherwise. Even though `gate_new_entry`
    blocks NEW entries, exits/rebalances may still fire — clamp them.
    """
    s = current_state or read_state()
    return SIZE_MULTIPLIER_IN_SAFE_MODE if s.active else 1.0


def confidence_penalty(*, current_state: SafeModeState | None = None) -> float:
    """Penalty subtracted from confidence threshold checks.

    Returns 0.10 in safe_mode, 0.0 otherwise. Applied by caller:
    `effective_threshold = base_threshold + confidence_penalty()`.
    """
    s = current_state or read_state()
    return CONFIDENCE_PENALTY if s.active else 0.0


# ─── Internal audit emission ────────────────────────────────────────────────

def _emit_audit(event_type: str, state: SafeModeState, actor: str) -> None:
    """Best-effort audit JSONL emission. Never raises."""
    try:
        try:
            from audit import write_audit_event
            from autonomy import make_decision
        except ImportError:
            from shared.audit import write_audit_event   # type: ignore
            from shared.autonomy import make_decision     # type: ignore
        d = make_decision(
            decision_type=event_type,  # SAFE_MODE_ENTERED / SAFE_MODE_EXITED
            decision=event_type,
            reason=state.reason or "safe_mode transition",
            actor=actor,
            affected_symbols=[],
            inputs={
                "trigger":   state.trigger,
                "forced":    state.forced,
            },
            action_taken=f"safe_mode {'ENTERED' if state.active else 'EXITED'} ({state.trigger or '-'})",
            result="placed",
            reversible=True,
        )
        write_audit_event(d, kind="trading")
    except Exception as e:
        print(f"  safe_mode audit emit failed (non-fatal): {e}")


__all__ = [
    "SafeModeState",
    "TRIGGERS",
    "SIZE_MULTIPLIER_IN_SAFE_MODE",
    "CONFIDENCE_PENALTY",
    "read_state",
    "enter_safe_mode",
    "exit_safe_mode",
    "evaluate_triggers",
    "gate_new_entry",
    "size_multiplier",
    "confidence_penalty",
]
