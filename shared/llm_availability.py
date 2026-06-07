"""v3.22 (2026-06-07) — LLM availability tracker + operator escalation.

After LLM Senior PM was unavailable 3 consecutive days (2026-06-05/06/07),
the deterministic adapter ran in isolation while the 14-day LLM override
lock prevented even legitimate SILENT-strategy fixes (e.g. crypto-momentum
not firing on BTC RSI 7.6).

This module:
- Tracks consecutive_failures in runtime_state.json::llm_availability
- After 2 consecutive failures → enqueue REVIEW_LLM_OUTAGE (severity P0)
- After 3 + a SILENT strategy with active LLM lock → enqueue
  REVIEW_SILENT_STRATEGY_LOCK (severity P1)
- NEVER auto-clears the LLM override lock — operator-only

INVARIANTS
----------
- LLM_OUTAGE_DOES_NOT_BLOCK_RISK_ENGINE = True
- LLM_OUTAGE_DOES_NOT_AUTO_CLEAR_OVERRIDE = True

Both are asserted by tests so any future caller cannot bypass them.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

LLM_OUTAGE_DOES_NOT_BLOCK_RISK_ENGINE = True
LLM_OUTAGE_DOES_NOT_AUTO_CLEAR_OVERRIDE = True

# Thresholds (tunable via env, never via runtime call sites).
P0_FAILURE_THRESHOLD = int(os.environ.get("LLM_AVAILABILITY_P0_THRESHOLD", "2"))
P1_FAILURE_THRESHOLD = int(os.environ.get("LLM_AVAILABILITY_P1_THRESHOLD", "3"))
SILENT_DAYS_FOR_LOCK_REVIEW = int(
    os.environ.get("LLM_AVAILABILITY_SILENT_DAYS_FOR_LOCK_REVIEW", "30")
)


def _read_section() -> dict:
    try:
        try:
            from runtime_state import read_section  # type: ignore
        except ImportError:
            from shared.runtime_state import read_section  # type: ignore
        s = read_section("llm_availability")
        return s if isinstance(s, dict) else {}
    except Exception:
        return {}


def _write_section(payload: dict) -> None:
    try:
        try:
            from runtime_state import write_section  # type: ignore
        except ImportError:
            from shared.runtime_state import write_section  # type: ignore
        write_section("llm_availability", payload, actor="llm-availability")
    except Exception:
        return


def _utc_iso(when: datetime | None = None) -> str:
    return (when or datetime.now(timezone.utc)).isoformat()


def _enqueue_action(action_type: str, severity: str, rationale: str,
                     evidence: list[str] | None = None) -> dict | None:
    """Append one operator-action queue row. Fail-soft."""
    try:
        try:
            from operator_action_queue import enqueue_action, make_action  # type: ignore
        except ImportError:
            from shared.operator_action_queue import (  # type: ignore
                enqueue_action, make_action,
            )
        action = make_action(
            action_type=action_type,
            severity=severity,
            source_module="llm_availability",
            rationale=rationale,
            evidence_links=evidence or [],
        )
        # Invariant: can_auto_apply must remain False.
        if action.get("can_auto_apply"):
            return None
        enqueue_action(action)
        return action
    except Exception:
        return None


def record_run(success: bool, reason: str = "", when: datetime | None = None) -> dict:
    """Update LLM availability state + escalate if needed.

    Returns the updated state dict.

    Per invariants, this function does NOT:
    - touch the risk engine
    - mutate any strategy lock
    - call alpaca_orders or close any position
    - flip EDGE_GATE_ENABLED
    """
    state = _read_section()
    failures = int(state.get("consecutive_failures", 0))
    history = state.get("history") if isinstance(state.get("history"), list) else []

    now = _utc_iso(when)
    entry = {"at": now, "success": bool(success), "reason": str(reason)[:200]}
    history.append(entry)
    # Keep last 30 entries only — fail-soft tail trim.
    if len(history) > 30:
        history = history[-30:]

    if success:
        failures = 0
    else:
        failures += 1

    new_state = {
        "consecutive_failures": failures,
        "last_run_at": now,
        "last_success": success,
        "last_reason": str(reason)[:200],
        "history": history,
    }

    actions_enqueued: list[str] = []
    if not success:
        if failures >= P0_FAILURE_THRESHOLD:
            a = _enqueue_action(
                action_type="REVIEW_LLM_OUTAGE",
                severity="P0",
                rationale=(
                    f"LLM unavailable {failures} consecutive run(s). "
                    f"Reason: {reason}. Non-auto-apply by design."
                ),
                evidence=[f"runtime_state.json::llm_availability"],
            )
            if a:
                actions_enqueued.append("REVIEW_LLM_OUTAGE")

    new_state["actions_enqueued_this_run"] = actions_enqueued
    _write_section(new_state)
    return new_state


def escalate_silent_strategy_lock(strategy: str, silent_days: int,
                                    last_override_iso: str | None = None) -> dict | None:
    """Enqueue REVIEW_SILENT_STRATEGY_LOCK when conditions are met.

    Called by analyzer.py at SILENT-strategy detection time, AFTER record_run
    has updated the LLM availability counter. Returns the enqueued action
    dict if conditions are met, else None.

    Conditions (ALL must hold):
    - consecutive LLM failures >= P1_FAILURE_THRESHOLD
    - silent_days >= SILENT_DAYS_FOR_LOCK_REVIEW
    - strategy has an active LLM override lock (caller already verified)
    """
    state = _read_section()
    failures = int(state.get("consecutive_failures", 0))
    if failures < P1_FAILURE_THRESHOLD:
        return None
    if silent_days < SILENT_DAYS_FOR_LOCK_REVIEW:
        return None

    rationale = (
        f"Strategy '{strategy}' SILENT {silent_days} days + LLM override "
        f"lock active. LLM unavailable {failures} runs — cannot revise. "
        f"Review-gated by Multi-Agent Audit Board. Non-auto-apply by design."
    )
    return _enqueue_action(
        action_type="REVIEW_SILENT_STRATEGY_LOCK",
        severity="P1",
        rationale=rationale,
        evidence=[
            f"strategy={strategy}",
            f"silent_days={silent_days}",
            f"last_override_iso={last_override_iso or 'unknown'}",
        ],
    )


def get_state() -> dict:
    """Snapshot — read-only view of current availability state."""
    return _read_section()


__all__ = [
    "LLM_OUTAGE_DOES_NOT_BLOCK_RISK_ENGINE",
    "LLM_OUTAGE_DOES_NOT_AUTO_CLEAR_OVERRIDE",
    "P0_FAILURE_THRESHOLD",
    "P1_FAILURE_THRESHOLD",
    "SILENT_DAYS_FOR_LOCK_REVIEW",
    "record_run",
    "escalate_silent_strategy_lock",
    "get_state",
]
