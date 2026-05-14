"""
shared/defensive_mode.py — Kill-switch coordinator.

When account hits max_drawdown_defensive_mode_pct (-12% from peak) or
full_stop (-20%), this module coordinates:
  - emit notify_signal email with summary
  - persist `defensive_mode_armed: true` in state.json
  - (optionally) close speculative positions via Alpaca REST

CAREFUL: close_all_positions() requires the deterministic kill-switch
flag `kill_switch_armed=true` in state.json to prevent accidental
flat-everything on a transient API blip. The flag is set explicitly by
the operator via state-policy maintenance — never by signal-time code.

Entry monitors read `is_defensive_mode_active()` and skip new entries
when True. Existing exit monitors keep working (closes are always
permitted).
"""

import json
import os
from datetime import datetime, timezone

_REPO_ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_STATE_PATH = os.path.join(_REPO_ROOT, "learning-loop", "state.json")


def _read_state() -> dict:
    try:
        with open(_STATE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_state(state: dict) -> bool:
    try:
        with open(_STATE_PATH, "w") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        return True
    except OSError as e:
        print(f"  defensive_mode: write error: {e}")
        return False


def is_defensive_mode_active() -> bool:
    """Check state.json for defensive_mode_armed flag."""
    s = _read_state()
    return bool((s.get("defensive_mode") or {}).get("armed", False))


def is_full_stop_armed() -> bool:
    """Deterministic kill-switch flag for close-all-positions execution."""
    s = _read_state()
    return bool((s.get("defensive_mode") or {}).get("full_stop_armed", False))


def arm_defensive_mode(reason: str, source: str = "auto") -> bool:
    """
    Persist defensive_mode_armed=true in state.json with reason +
    timestamp. Idempotent (re-arms with new reason).
    """
    s = _read_state()
    s["defensive_mode"] = {
        "armed":     True,
        "reason":    reason,
        "source":    source,             # "auto" (rule-triggered) | "manual"
        "armed_at":  datetime.now(timezone.utc).isoformat(),
        "full_stop_armed": s.get("defensive_mode", {}).get("full_stop_armed", False),
    }
    if _write_state(s):
        print(f"  defensive_mode: ARMED ({source}): {reason}")
        return True
    return False


def disarm_defensive_mode() -> bool:
    """Clear defensive_mode flag (operator-only action)."""
    s = _read_state()
    if "defensive_mode" in s:
        s["defensive_mode"]["armed"] = False
        s["defensive_mode"]["disarmed_at"] = datetime.now(timezone.utc).isoformat()
        _write_state(s)
        print(f"  defensive_mode: DISARMED")
    return True


def check_and_arm_from_drawdown(account: dict | None = None,
                                  peak_equity: float | None = None) -> dict:
    """
    Composite check called by entry monitors. Reads max_drawdown_guard
    + (optionally) arms defensive_mode automatically.

    Returns:
      {
        "active":       bool,
        "level":        "OK" | "DEFENSIVE" | "FULL_STOP",
        "reason":       str,
        "armed_now":    bool,   # True if THIS call armed the mode
      }
    """
    try:
        from risk_guards import max_drawdown_guard
    except ImportError:
        from shared.risk_guards import max_drawdown_guard

    level, reason = max_drawdown_guard(account=account, peak_equity=peak_equity)
    already_armed = is_defensive_mode_active()
    armed_now = False
    if level in ("DEFENSIVE", "FULL_STOP") and not already_armed:
        arm_defensive_mode(reason, source="auto")
        armed_now = True
    return {
        "active":   level != "OK",
        "level":    level,
        "reason":   reason,
        "armed_now": armed_now,
    }
