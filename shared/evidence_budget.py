"""v3.21.0 (2026-06-04) — ETAP 9 — Evidence Budget.

WHY
---
Audit-board 2026-06-02 reaffirmed ``NOT_SAFE_FOR_LIVE_TRADING`` and the
cross-cutting theme STRAT-003 ("strategy validation deficit") emphasised
the need for *bounded* evidence production. Without explicit caps the
free-tier runner can be hammered by enthusiastic learning-loop heuristics
or runaway counterfactual sweeps. Worse, those sweeps can starve actual
safety reporting (kill-switch alerts, safe-mode transitions, P0 audit
findings) of CPU / disk / runtime budget.

This module is the deterministic *bounded-resource* layer for evidence
production. It does NOT raise risk thresholds, does NOT lower safety
gates, does NOT bypass the audit log, does NOT call paid APIs, and does
NOT introduce LLM into the runtime trading path. It is governed by
Multi-Agent Audit Board.

CONTRACT
--------
- Pure stdlib. Deterministic. Offline. Free-tier safe.
- ``check_budget(action_type, count=1)`` -> ``(allowed: bool, reason: str)``.
- Budget NEVER suppresses safety reports. See ``BUDGET_BYPASSES_SAFETY``
  and ``SAFETY_ACTION_TYPES``.
- Counters reset at UTC midnight (per-action ledger keyed on ISO date).
- State persisted to ``learning-loop/runtime_state.json::evidence_budget``
  via ``shared.runtime_state.update_section`` (writer = evidence-budget).
- Same input -> same allowed / same reason (deterministic).

LIMITS (deterministic, exported for tests)
------------------------------------------
``MAX_SHADOW_OBS_PER_DAY``         = 500
``MAX_VARIANTS_EVALUATED_PER_DAY`` = 20
``MAX_SYMBOLS_PER_STRATEGY``       = 30
``MAX_COUNTERFACTUALS_PER_RUN``    = 200
``MAX_WORKFLOW_RUNTIME_SECONDS``   = 600
``MAX_REPORT_SIZE_KB``             = 512

SAFETY BYPASS
-------------
``BUDGET_BYPASSES_SAFETY = True`` — invariant. Any ``action_type`` in
``SAFETY_ACTION_TYPES`` is ALWAYS allowed regardless of counters.
Examples: ``safety_report`` (kill-switch alert), ``safe_mode_transition``,
``p0_audit_finding``, ``emergency_close_audit``, ``audit_emit``.

NON-AUTO-APPLY
--------------
Budget rejections SURFACE the limit but do not mutate the strategy.
The Operator Action Queue (ETAP 10) is the only consumer that can
escalate a sustained limit hit to operator review. This module is
review-gated; it never auto-disables anything.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

# Local imports.
try:
    from runtime_state import read_section, write_section
except ImportError:  # pragma: no cover
    from shared.runtime_state import read_section, write_section  # type: ignore


_REPO_ROOT = Path(__file__).resolve().parent.parent


# ─── Limits (deterministic constants) ─────────────────────────────────────────

MAX_SHADOW_OBS_PER_DAY:         int = 500
MAX_VARIANTS_EVALUATED_PER_DAY: int = 20
MAX_SYMBOLS_PER_STRATEGY:       int = 30
MAX_COUNTERFACTUALS_PER_RUN:    int = 200
MAX_WORKFLOW_RUNTIME_SECONDS:   int = 600
MAX_REPORT_SIZE_KB:             int = 512


# ─── Safety bypass invariant ─────────────────────────────────────────────────

# Spec invariant: budget MUST NEVER suppress safety reports. Verified by
# unit tests and consulted by ``check_budget`` before any counter logic.
BUDGET_BYPASSES_SAFETY: bool = True


# ─── Action types ────────────────────────────────────────────────────────────

# Closed enum of consumable action types. ``check_budget`` returns the
# pair ``(False, "unknown_action_type:...")`` for anything else, which is
# itself non-fatal — callers are expected to fall back to safe behaviour.
ACTION_TYPES: frozenset[str] = frozenset({
    "shadow_observation",      # per-day, capped at MAX_SHADOW_OBS_PER_DAY
    "variant_evaluation",      # per-day, capped at MAX_VARIANTS_EVALUATED_PER_DAY
    "symbol_for_strategy",     # per-strategy lifetime, capped MAX_SYMBOLS_PER_STRATEGY
    "counterfactual_run",      # per-run, capped MAX_COUNTERFACTUALS_PER_RUN
    "workflow_runtime",        # per-run cumulative seconds, MAX_WORKFLOW_RUNTIME_SECONDS
    "report_size_kb",          # per-run, capped MAX_REPORT_SIZE_KB
})


# Safety action types — ALWAYS allowed. Order is irrelevant.
SAFETY_ACTION_TYPES: frozenset[str] = frozenset({
    "safety_report",
    "safe_mode_transition",
    "p0_audit_finding",
    "emergency_close_audit",
    "audit_emit",
    "kill_switch_alert",
})


# ─── Limit lookup ────────────────────────────────────────────────────────────

_LIMITS: Mapping[str, int] = {
    "shadow_observation":      MAX_SHADOW_OBS_PER_DAY,
    "variant_evaluation":      MAX_VARIANTS_EVALUATED_PER_DAY,
    "symbol_for_strategy":     MAX_SYMBOLS_PER_STRATEGY,
    "counterfactual_run":      MAX_COUNTERFACTUALS_PER_RUN,
    "workflow_runtime":        MAX_WORKFLOW_RUNTIME_SECONDS,
    "report_size_kb":          MAX_REPORT_SIZE_KB,
}


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        v = int(x)
        if v < 0:
            return default
        return v
    except (TypeError, ValueError):
        return default


def _is_per_day(action: str) -> bool:
    return action in {"shadow_observation", "variant_evaluation"}


def _is_per_run(action: str) -> bool:
    return action in {"counterfactual_run", "workflow_runtime",
                      "report_size_kb"}


def _is_per_strategy(action: str) -> bool:
    return action == "symbol_for_strategy"


# ─── State I/O ───────────────────────────────────────────────────────────────


def _state() -> dict:
    """Return the current ``evidence_budget`` runtime_state section."""
    s = read_section("evidence_budget")
    if not isinstance(s, dict):
        return {}
    return s


def _reset_for_new_day(state: dict) -> dict:
    """Reset per-day counters when the stored ISO date is stale."""
    today = _today_iso()
    if state.get("date") != today:
        state = {
            "date":                        today,
            "shadow_observation":          0,
            "variant_evaluation":          0,
            "symbol_for_strategy":         dict(state.get("symbol_for_strategy", {})),
            "counterfactual_run":          0,
            "workflow_runtime":            0,
            "report_size_kb":              0,
            "safety_bypasses":             _safe_int(state.get("safety_bypasses", 0)),
        }
    return state


def _persist(state: dict) -> None:
    try:
        write_section("evidence_budget", state, actor="evidence-budget")
    except Exception:
        # Fail-soft: budget tracking must not break the call path.
        pass


# ─── Public API ──────────────────────────────────────────────────────────────


def get_state() -> dict:
    """Return the (possibly reset) budget snapshot for today."""
    s = _state()
    return _reset_for_new_day(s)


def check_budget(action_type: str, count: int = 1) -> tuple[bool, str]:
    """Deterministic budget gate.

    Returns ``(allowed, reason)`` for the requested action / count.

    Contract:
      - Safety action types are ALWAYS allowed (invariant
        ``BUDGET_BYPASSES_SAFETY``); the safety counter is incremented
        so we can detect surges in monitoring.
      - Unknown action types are denied with ``unknown_action_type:...``.
      - Per-day actions reset at UTC midnight (one-shot).
      - Per-strategy actions ``symbol_for_strategy`` use a dict keyed
        on the strategy name supplied via env var
        ``EVIDENCE_BUDGET_STRATEGY`` (caller responsibility). When the
        env var is absent we use ``__default__``.
      - Same input -> same (allowed, reason): deterministic.

    Side effects: increments the corresponding counter and persists via
    ``runtime_state.update_section``. Persistence failures do not raise.
    """
    n = _safe_int(count, 1)
    if n <= 0:
        return True, "no-op zero count"

    # Safety bypass — never gated by counters.
    if action_type in SAFETY_ACTION_TYPES:
        s = get_state()
        s["safety_bypasses"] = _safe_int(s.get("safety_bypasses", 0)) + n
        _persist(s)
        return True, f"safety_action:{action_type} bypasses budget"

    if action_type not in ACTION_TYPES:
        return False, f"unknown_action_type:{action_type}"

    s = get_state()

    if _is_per_day(action_type):
        used  = _safe_int(s.get(action_type, 0))
        limit = _LIMITS[action_type]
        if used + n > limit:
            return False, f"per_day_limit:{action_type}={used}+{n}>{limit}"
        s[action_type] = used + n
        _persist(s)
        return True, f"per_day_ok:{action_type}={s[action_type]}/{limit}"

    if _is_per_run(action_type):
        used  = _safe_int(s.get(action_type, 0))
        limit = _LIMITS[action_type]
        if used + n > limit:
            return False, f"per_run_limit:{action_type}={used}+{n}>{limit}"
        s[action_type] = used + n
        _persist(s)
        return True, f"per_run_ok:{action_type}={s[action_type]}/{limit}"

    if _is_per_strategy(action_type):
        strategy = os.environ.get("EVIDENCE_BUDGET_STRATEGY", "__default__")
        per = dict(s.get("symbol_for_strategy", {}))
        used  = _safe_int(per.get(strategy, 0))
        limit = _LIMITS[action_type]
        if used + n > limit:
            return False, (
                f"per_strategy_limit:{strategy}:"
                f"{action_type}={used}+{n}>{limit}"
            )
        per[strategy] = used + n
        s["symbol_for_strategy"] = per
        _persist(s)
        return True, (
            f"per_strategy_ok:{strategy}:"
            f"{action_type}={per[strategy]}/{limit}"
        )

    # Defensive: shouldn't reach here.
    return False, f"unrecognised_scope:{action_type}"


def get_limit(action_type: str) -> int | None:
    """Return the static limit for ``action_type`` (or None)."""
    return _LIMITS.get(action_type)


def reset_run_counters() -> None:
    """Reset per-run counters (counterfactual_run / workflow_runtime /
    report_size_kb). Called at the start of every workflow that produces
    evidence. Per-day and per-strategy counters are NOT touched.
    """
    s = get_state()
    for k in ("counterfactual_run", "workflow_runtime", "report_size_kb"):
        s[k] = 0
    _persist(s)


def render_report() -> str:
    """Return a deterministic markdown snapshot of the current budget.

    The shape is stable so report-consuming agents can diff it.
    """
    s = get_state()
    lines: list[str] = []
    lines.append("# Evidence Budget — current snapshot")
    lines.append("")
    lines.append(f"- date: {s.get('date', '?')}")
    lines.append(f"- BUDGET_BYPASSES_SAFETY: {BUDGET_BYPASSES_SAFETY}")
    lines.append("")
    lines.append("## Counters")
    lines.append("")
    lines.append("| Action | Used | Limit |")
    lines.append("|---|---:|---:|")
    for action in sorted(_LIMITS):
        if action == "symbol_for_strategy":
            per = s.get("symbol_for_strategy", {}) or {}
            for k in sorted(per):
                lines.append(
                    f"| symbol_for_strategy[{k}] "
                    f"| {_safe_int(per.get(k, 0))} "
                    f"| {_LIMITS[action]} |"
                )
            if not per:
                lines.append(
                    f"| symbol_for_strategy[*] | 0 | {_LIMITS[action]} |"
                )
            continue
        lines.append(
            f"| {action} | {_safe_int(s.get(action, 0))} | {_LIMITS[action]} |"
        )
    lines.append("")
    lines.append(
        f"safety_bypasses (always allowed): "
        f"{_safe_int(s.get('safety_bypasses', 0))}"
    )
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "MAX_SHADOW_OBS_PER_DAY",
    "MAX_VARIANTS_EVALUATED_PER_DAY",
    "MAX_SYMBOLS_PER_STRATEGY",
    "MAX_COUNTERFACTUALS_PER_RUN",
    "MAX_WORKFLOW_RUNTIME_SECONDS",
    "MAX_REPORT_SIZE_KB",
    "BUDGET_BYPASSES_SAFETY",
    "ACTION_TYPES",
    "SAFETY_ACTION_TYPES",
    "check_budget",
    "get_limit",
    "get_state",
    "reset_run_counters",
    "render_report",
]
