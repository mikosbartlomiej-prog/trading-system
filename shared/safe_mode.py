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
    # v3.22 ETAP 9 (2026-06-15) — CRITICAL incident-pattern-detector findings
    "INCIDENT_P01_DUPLICATE_ALLOCATOR": "Incident P01 (duplicate allocator execution) detected",
    "INCIDENT_P02_NAKED_SHORT":         "Incident P02 (naked short on long-only whitelist) detected",
    "INCIDENT_P13_BRACKET_INTERLOCK":   "Incident P13 (bracket interlock blocked close) detected",
}

# v3.22 ETAP 9 (2026-06-15) — trigger constants used by incident detector
# so it does not need to encode the magic strings inline.
TRIGGER_INCIDENT_P01_DUPLICATE_ALLOCATOR = "INCIDENT_P01_DUPLICATE_ALLOCATOR"
TRIGGER_INCIDENT_P02_NAKED_SHORT         = "INCIDENT_P02_NAKED_SHORT"
TRIGGER_INCIDENT_P13_BRACKET_INTERLOCK   = "INCIDENT_P13_BRACKET_INTERLOCK"

# Dedupe window for the incident-driven triggers — same trigger within
# this many seconds is treated as already active and no fresh entry is
# written. Spec §9: 60 minutes.
INCIDENT_DEDUPE_WINDOW_SECONDS = 60 * 60

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

    Default to ACTIVE on parse error (safer). The module docstring at
    the top of this file commits to this contract — any error in
    read/parse is treated as "we cannot prove safety is OK, therefore
    safe_mode is ACTIVE so new entries are blocked".

    A missing section / cleanly-empty dict / explicit inactive payload
    all read as inactive. Only an actual parse error or a non-dict
    section escalates to ACTIVE.
    """
    try:
        raw = read_section(SAFE_MODE_SECTION)
    except Exception:
        # Hard parse failure inside runtime_state — default ACTIVE per docstring.
        return SafeModeState(
            active=True,
            reason="safe_mode: read_section raised — defaulting to ACTIVE per fail-closed contract",
            entered_at=_now_iso(),
            trigger="OPERATOR",  # closest enum entry meaning "unknown forced state"
            forced=False,
        )

    # Treat missing section / cleanly-empty dict as inactive (cold-start
    # behaviour: the system is not in safe_mode until something puts it
    # there). This matches the v3.12.0 behaviour the rest of the code
    # already depends on for fresh runtime_state.json files.
    if raw is None or raw == {}:
        return SafeModeState.inactive()

    if not isinstance(raw, dict):
        # Section present but not a dict → parse error per docstring.
        return SafeModeState(
            active=True,
            reason=f"safe_mode: section type={type(raw).__name__} — defaulting to ACTIVE per fail-closed contract",
            entered_at=_now_iso(),
            trigger="OPERATOR",
            forced=False,
        )

    try:
        return SafeModeState(
            active=bool(raw.get("active", False)),
            reason=str(raw.get("reason", "")),
            entered_at=raw.get("entered_at"),
            trigger=raw.get("trigger"),
            forced=bool(raw.get("forced", False)),
        )
    except Exception:
        # Per-field parse failure → ACTIVE per docstring.
        return SafeModeState(
            active=True,
            reason="safe_mode: per-field parse failure — defaulting to ACTIVE per fail-closed contract",
            entered_at=_now_iso(),
            trigger="OPERATOR",
            forced=False,
        )


def _seconds_since_iso(iso_ts: str | None) -> float | None:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        return None


def enter_safe_mode(trigger: str, reason: str, actor: str = "safe_mode",
                    *, dedupe_seconds: float | None = None) -> SafeModeState:
    """Flip safe_mode ON with audit emission.

    Idempotent: if already active with the same trigger, no-op (no
    spam audit entries).

    v3.22 ETAP 9 (2026-06-15) dedupe-window contract:
      - When `dedupe_seconds` is supplied (incident-pattern-detector
        passes ``INCIDENT_DEDUPE_WINDOW_SECONDS``), callers asking to
        enter with the SAME trigger within that window get a no-op
        (no re-write, no fresh audit event). This stops detector spam.
      - When `dedupe_seconds` is None, the legacy "same trigger →
        no-op" behaviour is preserved.
    """
    current = read_state()

    # Legacy idempotency — same trigger, already active, not operator-forced.
    if current.active and current.trigger == trigger and not current.forced:
        if dedupe_seconds is None:
            return current
        age = _seconds_since_iso(current.entered_at)
        # If we cannot read age, treat as "fresh" (i.e. no dedupe — still no-op
        # because trigger matches the existing active one).
        if age is None:
            return current
        if age < dedupe_seconds:
            # Within dedupe window → silent no-op.
            return current
        # Outside dedupe window → re-stamp entered_at + emit a fresh audit
        # event so operators can see the trigger renewed (still ACTIVE,
        # just visible again).
        # Fall through to write path below.

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


def enter(trigger: str, reason: str, actor: str = "safe_mode",
          *, dedupe_seconds: float | None = None) -> SafeModeState:
    """v3.22 ETAP 9 convenience alias matching the spec's call shape.

    `incident_pattern_detector.py` calls
    ``safe_mode.enter(trigger=..., reason=...)``. This forwards to
    `enter_safe_mode` so the legacy name keeps working too.
    """
    return enter_safe_mode(trigger, reason, actor, dedupe_seconds=dedupe_seconds)


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
    "TRIGGER_INCIDENT_P01_DUPLICATE_ALLOCATOR",
    "TRIGGER_INCIDENT_P02_NAKED_SHORT",
    "TRIGGER_INCIDENT_P13_BRACKET_INTERLOCK",
    "INCIDENT_DEDUPE_WINDOW_SECONDS",
    "SIZE_MULTIPLIER_IN_SAFE_MODE",
    "CONFIDENCE_PENALTY",
    "read_state",
    "enter",
    "enter_safe_mode",
    "exit_safe_mode",
    "evaluate_triggers",
    "gate_new_entry",
    "size_multiplier",
    "confidence_penalty",
]
