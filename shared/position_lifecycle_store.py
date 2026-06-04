"""v3.17.0 (2026-06-04) — PositionState persistence helper.

Closes Task 6: wires shared/position_manager.py into exit-monitor by giving
the monitor a tiny, fail-soft helper that loads/saves per-symbol PositionState
to learning-loop/runtime_state.json::positions[<symbol>].

WHY a separate module:
  - position_manager.py is pure (no side effects, no I/O).
  - exit-monitor.py is already 700+ lines; we want lifecycle wiring isolated.
  - Both can be unit-tested independently. The helper has no Alpaca imports.

CONTRACT
  - Reads runtime_state.json via shared.runtime_state.read_section("positions").
  - Writes via shared.runtime_state.merge_section("positions", patch, actor=...).
  - Actor MUST be one of RUNTIME_STATE_ACTORS (state_policy.py). Exit-monitor
    uses "exit-monitor" (already allowlisted).
  - Persistence is BENIGN if it fails (logs, returns); position_manager re-
    derives state from Alpaca on next tick (lifecycle resets to INTAKE, which
    is the safest default — gives the system one grace period, then arms).

NEVER
  - Place orders here.
  - Mutate state in place — every save is a fresh dict to keep audit JSONL
    deterministic (no hidden references).
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict
from typing import Optional

# Add parent's "shared" dir on path so this module is importable both as
# `shared.position_lifecycle_store` (tests) and as bare `position_lifecycle_store`
# (when exit-monitor sys.path-injects shared/).
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from position_manager import PositionState, VALID_STATES, INTAKE, ARMED, TRAILING
except ImportError:  # pragma: no cover
    from shared.position_manager import PositionState, VALID_STATES, INTAKE, ARMED, TRAILING  # type: ignore

try:
    from runtime_state import read_section, merge_section, write_section
except ImportError:  # pragma: no cover
    from shared.runtime_state import read_section, merge_section, write_section  # type: ignore


_SECTION = "positions"
_DEFAULT_ACTOR = "exit-monitor"


def _coerce_float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _coerce_str(v, default="") -> str:
    if v is None:
        return default
    return str(v)


def load_position(symbol: str) -> Optional[PositionState]:
    """Load PositionState for `symbol` from runtime_state.json::positions.

    Returns None if the symbol has no prior entry (caller should `open_position`).
    Fail-soft: corrupt/missing entries return None.
    """
    if not symbol:
        return None
    try:
        section = read_section(_SECTION) or {}
        raw = section.get(symbol)
        if not isinstance(raw, dict):
            return None
        lifecycle = _coerce_str(raw.get("lifecycle"), INTAKE)
        if lifecycle not in VALID_STATES:
            lifecycle = INTAKE
        # Reconstruct the frozen dataclass. Provide safe defaults so a
        # truncated entry from an older schema doesn't crash the monitor.
        return PositionState(
            symbol=_coerce_str(raw.get("symbol"), symbol),
            lifecycle=lifecycle,
            opened_at_iso=_coerce_str(raw.get("opened_at_iso")),
            entry_price=_coerce_float(raw.get("entry_price")),
            entry_qty=_coerce_float(raw.get("entry_qty")),
            entry_confidence=(
                None if raw.get("entry_confidence") is None
                else _coerce_float(raw.get("entry_confidence"))
            ),
            intent=_coerce_str(raw.get("intent"), "swing"),
            last_eval_at_iso=_coerce_str(raw.get("last_eval_at_iso")),
            current_price=_coerce_float(raw.get("current_price")),
            current_pl_pct=_coerce_float(raw.get("current_pl_pct")),
            peak_price=_coerce_float(raw.get("peak_price")),
            peak_pl_pct=_coerce_float(raw.get("peak_pl_pct")),
            trough_price=_coerce_float(raw.get("trough_price")),
            trough_pl_pct=_coerce_float(raw.get("trough_pl_pct")),
            time_stop_hours=_coerce_float(raw.get("time_stop_hours"), 48.0),
            time_at_eval_hours=_coerce_float(raw.get("time_at_eval_hours")),
            confidence_now=(
                None if raw.get("confidence_now") is None
                else _coerce_float(raw.get("confidence_now"))
            ),
            profile_quality_now=(
                None if raw.get("profile_quality_now") is None
                else _coerce_float(raw.get("profile_quality_now"))
            ),
            warnings=tuple(raw.get("warnings") or ()),
        )
    except Exception as e:  # fail-soft — never crash exit-monitor
        print(f"  [pos-store] load failed for {symbol}: {type(e).__name__}: {e}")
        return None


def save_position(state: PositionState, *, actor: str = _DEFAULT_ACTOR,
                    next_lifecycle: Optional[str] = None) -> bool:
    """Persist `state` (optionally with a new lifecycle) under positions[<symbol>].

    Returns True on success, False on persistence failure (always non-fatal).
    """
    if state is None or not state.symbol:
        return False
    if next_lifecycle and next_lifecycle in VALID_STATES:
        snapshot = asdict(state)
        snapshot["lifecycle"] = next_lifecycle
    else:
        snapshot = asdict(state)
    # tuples (warnings) JSON-serialize as lists; that's fine
    try:
        section = read_section(_SECTION) or {}
        section[state.symbol] = snapshot
        # write_section is authoritative (overwrites entire section), which is
        # what we want — merge_section would not allow key REMOVAL on a future
        # call, so we use the same write path for both save + remove to keep
        # semantics consistent.
        write_section(_SECTION, section, actor=actor)
        return True
    except Exception as e:
        print(f"  [pos-store] save failed for {state.symbol}: {type(e).__name__}: {e}")
        return False


def remove_position(symbol: str, *, actor: str = _DEFAULT_ACTOR) -> bool:
    """Drop the entry for `symbol`. Used after a successful FULL_EXIT close.

    Idempotent: removing a missing entry is a no-op success.
    """
    if not symbol:
        return False
    try:
        section = read_section(_SECTION) or {}
        if symbol not in section:
            return True
        section.pop(symbol, None)
        # Use write_section (authoritative overwrite) — merge_section can't
        # delete keys because it only does dict.update(patch).
        write_section(_SECTION, section, actor=actor)
        return True
    except Exception as e:
        print(f"  [pos-store] remove failed for {symbol}: {type(e).__name__}: {e}")
        return False


def all_position_symbols() -> list[str]:
    """Return list of currently-tracked symbols (for ops dashboards / tests)."""
    try:
        section = read_section(_SECTION) or {}
        return sorted(s for s in section.keys() if isinstance(s, str))
    except Exception:
        return []


__all__ = [
    "load_position",
    "save_position",
    "remove_position",
    "all_position_symbols",
]
