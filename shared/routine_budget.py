"""
RoutineBudget — daily Anthropic Routine call cap with priority tiers.

Problem this solves (operational risk):
  Anthropic Routines have a hard 15-call/day limit. Currently the system
  uses ~7-11 calls/day (daily-learning 3-round dialog + occasional
  Reddit/Crypto curator + Sunday weekly retro). On a busy day with many
  curator candidates this can spike toward 15 and silently start
  returning HTTP 429, breaking the calling monitor. We want a
  client-side cap that gracefully refuses calls before the broker does,
  with priority awareness so daily-learning never starves under curator
  pressure.

Tier scheme (configured in config/routine_budget.json):
  P0 essential   — daily-learning Senior PM + Challenger + revise (3 calls)
  P1 important   — weekly-retro (Sundays, 3 calls) + legacy fallbacks
  P2 optional    — Reddit Curator, Crypto Curator, twitter-curator

Persistence:
  Counter lives in learning-loop/runtime_state.json::routine_budget,
  shared writer pattern (exit-monitor commits the file every 5 min, all
  other monitors read + merge). Daily auto-reset on first call of a new
  UTC date.

Public API:
    can_call(routine_name, priority='P2') -> tuple[bool, str]
        Pre-call check. Returns (allowed, reason).
    record_call(routine_name, priority='P2') -> dict
        Post-call increment. Returns updated counters dict.
    get_state() -> dict
        Read-only snapshot of today's counters + tier remaining.
    reset_for_new_day() -> bool
        Idempotent. Called automatically by can_call() / record_call().

Fail-soft contract: every call site already handles the "LLM unavailable"
case. If runtime_state is unreadable / unwritable, can_call() returns
(True, "budget-tracking-disabled") and record_call() is a no-op. The
caller proceeds as if no budget exists. This is intentional — we never
want budget tracking to itself be a failure mode.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

try:
    from runtime_state import read_section, merge_section
except ImportError:                                                            # pragma: no cover
    from shared.runtime_state import read_section, merge_section  # type: ignore


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# ─── Config loader ───────────────────────────────────────────────────────────


_DEFAULT_CONFIG = {
    "daily_limit": 15,
    "buffer":      1,
    "tiers": {
        "P0_essential": {
            "cap": 4,
            "routines": [
                "daily-learning-pm",
                "daily-learning-challenger",
                "daily-learning-revise",
            ],
        },
        "P1_important": {
            "cap": 5,
            "routines": [
                "weekly-retro-pm",
                "weekly-retro-challenger",
                "weekly-retro-revise",
                "exit-monitor-fallback",
                "geo-monitor-fallback",
            ],
        },
        "P2_optional": {
            "cap": 5,
            "routines": [
                "reddit-curator",
                "crypto-curator",
                "twitter-curator",
            ],
        },
    },
}


def _load_config() -> dict:
    """Load config/routine_budget.json, fall back to in-module defaults."""
    path = os.path.join(_REPO_ROOT, "config", "routine_budget.json")
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict) or "daily_limit" not in raw:
            return _DEFAULT_CONFIG
        # Sanitize: strip _doc / _notes keys, validate tier structure.
        out = {
            "daily_limit": int(raw.get("daily_limit", 15)),
            "buffer":      int(raw.get("buffer", 1)),
            "tiers":       {},
        }
        for tname, tdef in (raw.get("tiers") or {}).items():
            if not isinstance(tdef, dict):
                continue
            out["tiers"][tname] = {
                "cap":      int(tdef.get("cap", 0)),
                "routines": list(tdef.get("routines") or []),
            }
        return out
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _DEFAULT_CONFIG


# ─── Internal: priority resolution ───────────────────────────────────────────


def _resolve_priority(routine_name: str, requested: str | None,
                       cfg: dict) -> str:
    """
    If caller passed `priority`, honour it. Otherwise look up the routine
    in tier definitions. Falls back to 'P2_optional' for unknown routines
    (most conservative — bucket them with lowest priority).
    """
    if requested:
        # Normalise: accept P0 / P0_essential / p0 / "P0 essential"
        norm = requested.strip().upper().replace(" ", "_")
        for tname in cfg["tiers"]:
            if tname.upper().startswith(norm):
                return tname
    for tname, tdef in cfg["tiers"].items():
        if routine_name in tdef["routines"]:
            return tname
    return "P2_optional"


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ─── State helpers ───────────────────────────────────────────────────────────


def _read_state() -> dict:
    """
    Return today's counter dict.  Empty/old state is auto-reset.

    Shape:
        {
          "date": "2026-05-14",
          "total":  3,
          "by_tier":    {"P0_essential": 3, "P1_important": 0, "P2_optional": 0},
          "by_routine": {"daily-learning-pm": 1, ...},
          "last_updated": "...iso..."
        }
    """
    s = read_section("routine_budget") or {}
    today = _today_iso()
    if s.get("date") != today:
        # Fresh day → reset.
        return {
            "date":         today,
            "total":        0,
            "by_tier":      {},
            "by_routine":   {},
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
    # Ensure required fields exist (corrupt state defensive default).
    s.setdefault("total",        0)
    s.setdefault("by_tier",      {})
    s.setdefault("by_routine",   {})
    s.setdefault("last_updated", datetime.now(timezone.utc).isoformat())
    return s


def _persist_state(state: dict, actor: str = "intraday-monitor") -> bool:
    """
    Best-effort persist. Returns True on success, False if runtime_state
    is not writable (no-op; caller already updated in-memory).
    """
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    try:
        merge_section("routine_budget", state, actor=actor)
        return True
    except Exception:
        return False


# ─── Public API ───────────────────────────────────────────────────────────────


def get_state() -> dict:
    """
    Return today's snapshot with derived `remaining` fields. Read-only.
    """
    cfg   = _load_config()
    state = _read_state()
    daily = cfg["daily_limit"]
    buf   = cfg["buffer"]

    remaining_total = max(0, daily - buf - state["total"])
    remaining_by_tier = {}
    for tname, tdef in cfg["tiers"].items():
        used = int(state["by_tier"].get(tname, 0))
        remaining_by_tier[tname] = max(0, tdef["cap"] - used)

    return {
        "date":            state["date"],
        "total_used":      state["total"],
        "daily_limit":     daily,
        "buffer":          buf,
        "remaining_total": remaining_total,
        "by_tier":         dict(state["by_tier"]),
        "by_routine":      dict(state["by_routine"]),
        "remaining_by_tier": remaining_by_tier,
        "last_updated":    state["last_updated"],
    }


def can_call(routine_name: str, priority: str | None = None,
             actor: str = "intraday-monitor") -> tuple[bool, str]:
    """
    Pre-call gate. Returns (allowed: bool, reason: str).

    Decision tree:
      1. If runtime_state unreadable → (True, "budget-disabled") fail-open.
      2. If total + buffer ≥ daily_limit → (False, "daily cap reached")
      3. If tier_cap reached for this tier → (False, "tier cap reached")
      4. Else → (True, "budget OK")
    """
    cfg  = _load_config()
    tier = _resolve_priority(routine_name, priority, cfg)
    try:
        state = _read_state()
    except Exception:
        return True, "budget-tracking-disabled (state unreadable)"

    daily = cfg["daily_limit"]
    buf   = cfg["buffer"]
    tier_def = cfg["tiers"].get(tier, {"cap": 0, "routines": []})

    used_total = int(state.get("total", 0))
    used_tier  = int(state.get("by_tier", {}).get(tier, 0))

    if used_total >= (daily - buf):
        return False, (
            f"daily routine cap reached ({used_total}/{daily} used, "
            f"buffer={buf} reserved)"
        )

    if used_tier >= tier_def["cap"]:
        return False, (
            f"tier {tier} cap reached ({used_tier}/{tier_def['cap']} used; "
            f"daily total {used_total}/{daily - buf})"
        )

    remaining_after = daily - buf - used_total - 1
    return True, (
        f"budget OK ({used_total + 1}/{daily - buf} after this call; "
        f"tier {tier} {used_tier + 1}/{tier_def['cap']}; "
        f"{remaining_after} remaining total)"
    )


def record_call(routine_name: str, priority: str | None = None,
                actor: str = "intraday-monitor") -> dict:
    """
    Increment counters and persist. Returns the in-memory post-increment
    snapshot (so callers see what was attempted even if persistence
    fails). Never raises. Persistence is best-effort.
    """
    cfg   = _load_config()
    tier  = _resolve_priority(routine_name, priority, cfg)
    state = _read_state()

    state["total"]        = int(state.get("total", 0)) + 1
    state["by_tier"][tier] = int(state["by_tier"].get(tier, 0)) + 1
    state["by_routine"][routine_name] = (
        int(state["by_routine"].get(routine_name, 0)) + 1
    )

    _persist_state(state, actor=actor)

    # Build the same shape get_state() returns, but from in-memory state
    # (so the caller sees their increment even if persistence failed).
    daily = cfg["daily_limit"]
    buf   = cfg["buffer"]
    remaining_by_tier = {}
    for tname, tdef in cfg["tiers"].items():
        used = int(state["by_tier"].get(tname, 0))
        remaining_by_tier[tname] = max(0, tdef["cap"] - used)
    return {
        "date":            state["date"],
        "total_used":      state["total"],
        "daily_limit":     daily,
        "buffer":          buf,
        "remaining_total": max(0, daily - buf - state["total"]),
        "by_tier":         dict(state["by_tier"]),
        "by_routine":      dict(state["by_routine"]),
        "remaining_by_tier": remaining_by_tier,
        "last_updated":    state["last_updated"],
    }


def reset_for_new_day(actor: str = "intraday-monitor") -> bool:
    """
    Force a reset (idempotent — _read_state() already auto-resets on
    date change). Useful for tests or manual operator intervention.
    Returns True on successful persist.
    """
    fresh = {
        "date":         _today_iso(),
        "total":        0,
        "by_tier":      {},
        "by_routine":   {},
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    return _persist_state(fresh, actor=actor)


# ─── Audit emission ──────────────────────────────────────────────────────────


def emit_audit_event(event_type: str, routine_name: str, decision: str,
                     reason: str, state_snapshot: dict | None = None) -> None:
    """
    Append to journal/autonomy/YYYY-MM-DD.jsonl. Best-effort — audit
    write must never break the call path.
    """
    try:
        from audit import write_audit_event
    except ImportError:
        try:
            from shared.audit import write_audit_event  # type: ignore
        except ImportError:
            return
    try:
        payload = {
            "ts":           datetime.now(timezone.utc).isoformat(),
            "decision":     f"ROUTINE_BUDGET_{decision}",
            "event_type":   event_type,
            "actor":        "routine_budget",
            "routine":      routine_name,
            "reason":       reason,
        }
        if state_snapshot is not None:
            payload["state"] = {
                "total_used":      state_snapshot.get("total_used"),
                "daily_limit":     state_snapshot.get("daily_limit"),
                "remaining_total": state_snapshot.get("remaining_total"),
                "remaining_by_tier": state_snapshot.get("remaining_by_tier"),
            }
        write_audit_event(payload, kind="trading")
    except Exception:
        pass


# ─── Combined helper ─────────────────────────────────────────────────────────


def check_and_record(routine_name: str, priority: str | None = None,
                     actor: str = "intraday-monitor") -> tuple[bool, str, dict]:
    """
    Convenience for callers that want the full flow in one shot:
      1. can_call → if False, emit BLOCK audit + return (False, reason, state)
      2. otherwise → record_call → emit ALLOW audit + return (True, reason, state)

    Most call sites use this. Use can_call/record_call separately only
    when the routine call may fail and you want to charge the budget
    only on successful invocation.
    """
    ok, reason = can_call(routine_name, priority=priority, actor=actor)
    if not ok:
        state = get_state()
        emit_audit_event("BLOCK", routine_name, "BLOCK", reason, state)
        return False, reason, state
    state = record_call(routine_name, priority=priority, actor=actor)
    emit_audit_event("ALLOW", routine_name, "ALLOW", reason, state)
    return True, reason, state
