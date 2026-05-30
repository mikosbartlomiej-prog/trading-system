"""v3.12.0 (2026-05-30) — Component heartbeat / liveness tracking.

WHY
---
System has 11 monitors + allocator + analyzer + remediation, but no
single place to ask "what's alive right now?". monitor-health workflow
introspects GitHub Actions runs, but the SYSTEM ITSELF cannot answer
"is the crypto-monitor heartbeat fresh?" during a decision.

This module is a tiny, fail-soft heartbeat registry stored in
runtime_state.json::heartbeat. Each component pings on every successful
run; consumers read staleness to feed:
  * shared/confidence.py::score_system_health() — system_health component
  * shared/safe_mode.py — audit_gap / data freshness triggers
  * scripts/session_report.py — end-of-session liveness summary

CONTRACT
--------
heartbeat section in runtime_state.json:
{
  "<component_name>": {
    "last_seen_iso": "2026-05-30T07:45:00+00:00",
    "last_status":   "ok" | "warn" | "error",
    "last_message":  "free-text diagnostic",
    "pings_today":   42,
  }
}

ping(component, status="ok", message="") — call after monitor's main task
read() — return full dict
stale(component, max_age_seconds=600) — bool, True if last_seen older
alive_count(max_age_seconds=600) — count of components alive
all_components() — list of component names

Fail-soft: any error in read/write does NOT crash the caller.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

try:
    from runtime_state import read_section, write_section
except ImportError:
    try:
        from shared.runtime_state import read_section, write_section
    except ImportError:
        def read_section(name):  # type: ignore
            return None
        def write_section(name, data, actor=""):  # type: ignore
            return None


HEARTBEAT_SECTION = "heartbeat"

# Default staleness threshold per component class
# (overridable in calls).
DEFAULT_STALENESS_SECONDS = 600  # 10 min (most monitors run every 5 min)

# Components the system EXPECTS to see alive during a market session.
# Used by alive_count() / score_system_health() to know total population.
EXPECTED_COMPONENTS = (
    "crypto-monitor",
    "defense-monitor",
    "twitter-monitor",
    "reddit-monitor",
    "geo-monitor",
    "politician-monitor",
    "options-monitor",
    "options-exit-monitor",
    "price-monitor",
    "exit-monitor",
    "incident-pattern-detector",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


@dataclass
class HeartbeatEntry:
    last_seen_iso: str
    last_status: str
    last_message: str
    pings_today: int

    def to_dict(self) -> dict:
        return {
            "last_seen_iso": self.last_seen_iso,
            "last_status":   self.last_status,
            "last_message":  self.last_message,
            "pings_today":   self.pings_today,
        }


def read() -> dict:
    """Return entire heartbeat section. Fail-soft → empty dict."""
    try:
        raw = read_section(HEARTBEAT_SECTION) or {}
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def ping(component: str, *, status: str = "ok", message: str = "",
         actor: str = "heartbeat") -> None:
    """Record a heartbeat ping. Idempotent within same second.

    Fail-soft: any error → silent (don't crash the calling monitor).
    """
    if not component:
        return
    try:
        all_hb = read()
        today_iso = datetime.now(timezone.utc).date().isoformat()
        existing = all_hb.get(component) or {}
        # Reset pings_today on date change
        last_date = (existing.get("last_seen_iso") or "")[:10]
        pings = int(existing.get("pings_today", 0) or 0)
        if last_date != today_iso:
            pings = 0
        pings += 1
        all_hb[component] = HeartbeatEntry(
            last_seen_iso=_now_iso(),
            last_status=status,
            last_message=message[:200],
            pings_today=pings,
        ).to_dict()
        write_section(HEARTBEAT_SECTION, all_hb, actor=actor)
    except Exception as e:
        print(f"  heartbeat.ping({component}) failed (non-fatal): {e}")


def stale(component: str, max_age_seconds: float = DEFAULT_STALENESS_SECONDS) -> bool:
    """True if `component` has not pinged within `max_age_seconds`."""
    all_hb = read()
    entry = all_hb.get(component)
    if not entry:
        return True  # never pinged = stale
    try:
        last_iso = entry.get("last_seen_iso")
        if not last_iso:
            return True
        last_dt = datetime.fromisoformat(last_iso.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - last_dt).total_seconds()
        return age > max_age_seconds
    except Exception:
        return True


def age_seconds(component: str) -> float | None:
    """Seconds since last ping. None if never pinged or parse error."""
    all_hb = read()
    entry = all_hb.get(component)
    if not entry:
        return None
    try:
        last_iso = entry.get("last_seen_iso")
        if not last_iso:
            return None
        last_dt = datetime.fromisoformat(last_iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - last_dt).total_seconds()
    except Exception:
        return None


def alive_count(max_age_seconds: float = DEFAULT_STALENESS_SECONDS,
                  components: tuple = EXPECTED_COMPONENTS) -> tuple[int, int]:
    """Return (alive, total) for the given component list."""
    total = len(components)
    alive = sum(1 for c in components if not stale(c, max_age_seconds))
    return alive, total


def all_components() -> list:
    """All component names with a heartbeat entry."""
    return sorted(read().keys())


def health_snapshot(max_age_seconds: float = DEFAULT_STALENESS_SECONDS) -> dict:
    """Summary suitable for confidence.score_system_health() inputs.

    Returns dict with:
      alive: int
      total: int
      ratio: float in [0, 1]
      stale_components: list[str]
      worst_age_seconds: float | None
    """
    alive, total = alive_count(max_age_seconds)
    stale_list = [c for c in EXPECTED_COMPONENTS if stale(c, max_age_seconds)]
    ages = []
    for c in EXPECTED_COMPONENTS:
        a = age_seconds(c)
        if a is not None:
            ages.append(a)
    worst_age = max(ages) if ages else None
    return {
        "alive":             alive,
        "total":             total,
        "ratio":             alive / total if total else 0.0,
        "stale_components":  stale_list,
        "worst_age_seconds": worst_age,
    }


__all__ = [
    "HEARTBEAT_SECTION",
    "EXPECTED_COMPONENTS",
    "DEFAULT_STALENESS_SECONDS",
    "ping",
    "read",
    "stale",
    "age_seconds",
    "alive_count",
    "all_components",
    "health_snapshot",
]
