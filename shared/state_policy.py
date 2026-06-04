"""
Runtime state-write policy.

state.json (learning-loop adaptations) is an AUDIT-LOGGED snapshot of
adapter decisions. It must be written only by:
  - daily-learning  (cron, once per day)
  - daily-report    (read-only normally; allowed if it ever writes deltas)
  - weekly-retro
  - manual-maintenance (operator scripts)
  - tests / local dev (via STATE_WRITE_ACTOR=test)

Monitors at signal time must NEVER write state.json. Past bug: exit-monitor
and reddit-monitor were committing state.json every cron tick, turning git
into a hot runtime database. Rule C of the architecture spec forbids this.

Usage:
    from state_policy import assert_can_write_state
    assert_can_write_state("daily-learning", "applied 3 overrides")

The actor name is taken from the STATE_WRITE_ACTOR env var (workflows set
it explicitly) or passed in by callers. Unknown actors no-op + log warning.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Iterable

# Actors permitted to write `learning-loop/state.json` (the daily-adapter
# snapshot). High-frequency monitors are NOT here — they would race-condition
# git pushes. Intraday runtime state (peak P&L, MFE) lives in a separate file
# `learning-loop/runtime_state.json`; see shared/runtime_state.py + the
# RUNTIME_STATE_ACTORS allowlist below.
ALLOWED_ACTORS: frozenset[str] = frozenset({
    "daily-learning",
    "daily-report",
    "weekly-retro",
    "manual-maintenance",
    "test",
    "local-dev",
})

# Actors permitted to write `learning-loop/runtime_state.json` (the cron-
# scoped runtime snapshot — IntradayProfitGovernor state + position MFE +
# options trailing peaks). Exit-monitor is the natural custodian because it
# already polls every 5 min and consumes the data immediately.
RUNTIME_STATE_ACTORS: frozenset[str] = frozenset({
    "intraday-monitor",   # exit-monitor.yml sets STATE_WRITE_ACTOR=intraday-monitor
    "exit-monitor",       # legacy alias accepted for back-compat
    "options-exit-monitor",  # may merge its trailing-peak snapshot here
    # v3.12.0 (2026-05-30) — new runtime-state writers
    "safe_mode",          # shared/safe_mode.py writes safe_mode section
    "heartbeat",          # shared/heartbeat.py writes heartbeat section
    "confidence",         # shared/confidence.py writes confidence_history
    "session-reporter",   # scripts/session_report.py may emit snapshots
    # v3.18.0 (2026-06-04) — pre-open session planner
    "pre-open-planner",   # scripts/pre_open_session_planner.py writes pre_open_plan
    "pre-open-planner-test",  # unit-test variant
    "test",
    "local-dev",
})


class StateWriteForbidden(RuntimeError):
    """Raised when an unauthorized actor tries to write state."""


def current_actor() -> str:
    """Return the actor name from env (defaults to 'unknown')."""
    return (os.environ.get("STATE_WRITE_ACTOR") or "unknown").strip().lower()


def can_write_state(actor: str | None = None) -> bool:
    """Return True if `actor` is allowed to write state.json."""
    name = (actor or current_actor()).strip().lower()
    return name in ALLOWED_ACTORS


def assert_can_write_state(actor: str | None = None, reason: str = "") -> str:
    """
    Raise StateWriteForbidden if actor is not allowed.

    Returns the resolved actor name on success so callers can stamp
    `last_writer` directly:

        actor = assert_can_write_state("daily-learning", "applied overrides")
        state["last_writer"] = actor
    """
    name = (actor or current_actor()).strip().lower()
    if name not in ALLOWED_ACTORS:
        raise StateWriteForbidden(
            f"actor '{name}' is not in ALLOWED_ACTORS={sorted(ALLOWED_ACTORS)}. "
            f"reason='{reason}'. "
            f"Hint: set STATE_WRITE_ACTOR=daily-learning|daily-report|"
            f"weekly-retro|manual-maintenance in the workflow YAML."
        )
    return name


def stamp_state_metadata(state: dict, actor: str, reason: str = "") -> dict:
    """
    Mutate `state` with audit fields. Caller has already verified the
    actor via assert_can_write_state. Returns the same dict for chaining.

    Sets:
      state_version            — increments on each write (starts at 1)
      last_writer              — the actor that performed this write
      last_write_reason        — human-readable rationale
      last_validated_at        — UTC ISO timestamp (when stamped)
    """
    state["state_version"] = int(state.get("state_version") or 0) + 1
    state["last_writer"] = actor
    state["last_write_reason"] = reason or "(no reason given)"
    state["last_validated_at"] = datetime.now(timezone.utc).isoformat()
    return state


def safe_no_op(reason: str = "") -> None:
    """Log a friendly message when a monitor would have written state."""
    actor = current_actor()
    print(
        f"  [state-policy] skip-write actor='{actor}' reason='{reason}' "
        f"(allowed actors: {sorted(ALLOWED_ACTORS)})"
    )


def list_allowed_actors() -> Iterable[str]:
    return sorted(ALLOWED_ACTORS)


def can_write_runtime_state(actor: str | None = None) -> bool:
    """True if `actor` is allowed to write learning-loop/runtime_state.json.

    Runtime state is the 5-min governor/MFE/trailing snapshot — distinct
    from state.json. Allowlist is much wider because the data is ephemeral
    (re-derived from Alpaca on next tick if lost).
    """
    name = (actor or current_actor()).strip().lower()
    return name in RUNTIME_STATE_ACTORS


def assert_can_write_runtime_state(actor: str | None = None, reason: str = "") -> str:
    """Soft-asserts runtime-state write permission. Returns resolved actor.

    Unlike assert_can_write_state, the production failure mode here is
    BENIGN — runtime state can be re-built next tick — so callers may
    catch the exception and proceed without persistence rather than abort.
    """
    name = (actor or current_actor()).strip().lower()
    if name not in RUNTIME_STATE_ACTORS:
        raise StateWriteForbidden(
            f"actor '{name}' not in RUNTIME_STATE_ACTORS={sorted(RUNTIME_STATE_ACTORS)}. "
            f"reason='{reason}'. Hint: set STATE_WRITE_ACTOR=intraday-monitor "
            f"in the workflow YAML (exit-monitor / options-exit-monitor)."
        )
    return name
