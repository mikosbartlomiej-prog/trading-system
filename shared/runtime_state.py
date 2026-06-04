"""
Runtime state file for high-frequency monitors.

`learning-loop/state.json` is a DAILY snapshot of adapter decisions, write-
gated by shared.state_policy. It is committed once per day by daily-learning.
5-minute cron monitors cannot use it as a runtime database — they would burn
GitHub's rate limit on git pushes and race-condition each other.

This module owns a separate file:

    learning-loop/runtime_state.json

It holds ONLY ephemeral, intraday signals (peak P&L, position MFEs,
intraday governor FSM state). The file is:

  - Read by every monitor (no permission needed).
  - Written by the workflow that holds STATE_WRITE_ACTOR=intraday-monitor
    (currently exit-monitor.yml, which polls every 5 min and is the natural
    custodian of intraday equity state).
  - Persisted across cron ticks by a tiny post-step in exit-monitor.yml that
    git-commits ONLY this file with GITHUB_TOKEN (`.github/workflows/` is the
    OAuth-proxy-blocked path, but `learning-loop/runtime_state.json` is fine).
  - Reset at UTC midnight by the FSM owner (intraday_governor) — not by file
    deletion.

Other monitors call `read_runtime_state()` / `read_section(name)` only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_STATE_PATH = Path(
    os.environ.get("RUNTIME_STATE_PATH") or _REPO_ROOT / "learning-loop" / "runtime_state.json"
)


def _ensure_parent() -> None:
    RUNTIME_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)


def read_runtime_state() -> dict:
    """Return the whole runtime_state dict. Empty dict if file missing/corrupt."""
    try:
        with open(RUNTIME_STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            return {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def read_section(name: str) -> dict:
    """Return one top-level section (e.g. 'intraday_governor'). {} if absent."""
    s = read_runtime_state().get(name)
    return s if isinstance(s, dict) else {}


def write_section(name: str, payload: dict, actor: str = "intraday-monitor") -> None:
    """
    Overwrite one top-level section. Caller must already have asserted
    state-write permission via shared.state_policy (the section names listed
    in INTRADAY_SECTIONS are runtime-only and exempt from state_policy's
    state.json allowlist — they live in a different file).

    Safe to call repeatedly per cron run; final tick wins.
    """
    if not isinstance(payload, dict):
        raise TypeError(f"runtime_state section must be dict, got {type(payload).__name__}")
    _ensure_parent()
    current = read_runtime_state()
    current[name] = payload
    current["_last_writer"] = actor
    try:
        with open(RUNTIME_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, ensure_ascii=False, sort_keys=True)
    except OSError as e:
        # Fail-soft: monitor still functions in-process, just no persistence.
        print(f"  [runtime_state] save failed for '{name}': {e}")


def merge_section(name: str, patch: dict, actor: str = "intraday-monitor") -> dict:
    """
    Shallow-merge `patch` into section `name`. Returns the merged dict.
    Useful when several callers update different keys within the same tick.
    """
    if not isinstance(patch, dict):
        raise TypeError(f"runtime_state merge patch must be dict, got {type(patch).__name__}")
    current_section = read_section(name)
    current_section.update(patch)
    write_section(name, current_section, actor=actor)
    return current_section


# Recognised top-level sections. Adding a new one requires updating
# OPERATIONS_RUNBOOK.md so operators know what's persisted.
INTRADAY_SECTIONS = frozenset({
    "intraday_governor",   # IntradayProfitGovernor FSM snapshot
    "position_mfe",        # per-position MFE/retrace tracker
    "options_exit_trail",  # options-exit-monitor trailing peaks (migrated from state.json)
    "pdt_status",          # last classified PDT mode (read by all monitors)
    "routine_budget",      # daily Anthropic routine call tally (15/day cap)
    # v3.12.0 (2026-05-30) — new sections from confidence/safe_mode/heartbeat
    "safe_mode",           # runtime-operational safe mode (shared/safe_mode.py)
    "heartbeat",           # component liveness tracking (shared/heartbeat.py)
    "confidence_history",  # last N confidence reports (per-symbol)
    # v3.17.0 (2026-06-04) — position lifecycle state machine (FB-011)
    # Per-symbol PositionState snapshots persisted by exit-monitor; consumed
    # by shared.position_manager. Holds INTAKE/ARMED/TRAILING/INVALIDATING/
    # TIME_EXPIRED/CLOSED lifecycle + MFE/MAE marks + confidence-at-entry.
    "positions",
    # v3.18.0 P0-002 (2026-06-04) — exit-monitor PDT block cooldown.
    # Persists "<symbol>|<recommendation>|<decision>": "<iso-timestamp>"
    # entries so cooldown survives fresh GitHub Actions runner checkouts.
    # Was module-level dict in exit-monitor/monitor.py — reset every cron
    # tick → dedup never engaged → 36 audit events for one position per day.
    "pdt_cooldown",
})
