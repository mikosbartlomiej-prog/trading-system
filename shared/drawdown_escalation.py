"""v3.22 (2026-06-07) — Unrealized drawdown escalation (advisory only).

After equity dropped -4.27% / -$8,744 over 3 days with 0 attributed
closed trades, the existing daily_drawdown_guard (closed-trade based)
did not fire. This module surfaces unrealized mark-to-market drawdown
as a runtime signal that the allocator and operator can read.

CONTRACT
--------
- ADVISORY ONLY. Does NOT auto-close positions, does NOT place trades,
  does NOT mutate strategy state.
- Writes alert_level to runtime_state.json::drawdown_state.
- Enqueues operator actions on threshold transitions.
- Reads from learning-loop/history/*.md (equity snapshots) — no API.

INVARIANTS
----------
- DRAWDOWN_NEVER_AUTO_CLOSES = True
- DRAWDOWN_NEVER_RAISES_RISK = True
- DRAWDOWN_ADVISORY_ONLY = True
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

DRAWDOWN_NEVER_AUTO_CLOSES = True
DRAWDOWN_NEVER_RAISES_RISK = True
DRAWDOWN_ADVISORY_ONLY = True

# Alert levels (closed enum)
ALERT_NONE       = "NONE"
ALERT_WARN       = "WARN"
ALERT_RESTRICT   = "RESTRICT"
ALERT_EMERGENCY  = "EMERGENCY_REVIEW"
ALL_ALERT_LEVELS = frozenset({
    ALERT_NONE, ALERT_WARN, ALERT_RESTRICT, ALERT_EMERGENCY,
})

# Thresholds (tunable via env, never via runtime callers).
WARN_PCT      = float(os.environ.get("DRAWDOWN_WARN_PCT", "-3.0"))
RESTRICT_PCT  = float(os.environ.get("DRAWDOWN_RESTRICT_PCT", "-5.0"))
EMERGENCY_PCT = float(os.environ.get("DRAWDOWN_EMERGENCY_PCT", "-8.0"))


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        f = float(x)
        if f != f or f in (float("inf"), float("-inf")):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _classify_alert_level(equity_pct_change: float, attributed_closed_trades: int) -> str:
    """Map equity drawdown + closed-trade attribution to an alert level.

    Closed trades >= 1 do NOT lower the alert: the rule fires on
    unrealized drawdown regardless. Attribution is informational only.
    """
    pct = _safe_float(equity_pct_change, default=0.0)
    if pct <= EMERGENCY_PCT:
        return ALERT_EMERGENCY
    if pct <= RESTRICT_PCT:
        return ALERT_RESTRICT
    if pct <= WARN_PCT:
        return ALERT_WARN
    return ALERT_NONE


def _enqueue_drawdown_action(alert_level: str, equity_pct_change: float,
                              equity_now: float | None, equity_base: float | None,
                              closed_trades: int) -> dict | None:
    """Enqueue an operator action. Fail-soft."""
    try:
        try:
            from operator_action_queue import enqueue_action, make_action  # type: ignore
        except ImportError:
            from shared.operator_action_queue import (  # type: ignore
                enqueue_action, make_action,
            )
    except Exception:
        return None

    severity = {
        ALERT_WARN: "P2",
        ALERT_RESTRICT: "P1",
        ALERT_EMERGENCY: "P0",
    }.get(alert_level, "P2")

    rationale = (
        f"Unrealized equity drawdown {equity_pct_change:.2f}% "
        f"(equity_now=${equity_now}, base=${equity_base}, "
        f"closed_trades_attribution={closed_trades}). "
        f"Advisory only. Non-auto-apply by design. "
        f"Review-gated by Multi-Agent Audit Board."
    )

    try:
        action = make_action(
            action_type="REVIEW_OPEN_POSITIONS",
            severity=severity,
            source_module="drawdown_escalation",
            rationale=rationale,
            evidence_links=[
                f"runtime_state.json::drawdown_state",
                f"learning-loop/history/<date>.md::equity-gap",
            ],
        )
        if action.get("can_auto_apply"):
            return None
        enqueue_action(action)
        return action
    except Exception:
        return None


def _persist_state(alert_level: str, equity_pct_change: float,
                    equity_now: float | None, equity_base: float | None,
                    closed_trades: int) -> None:
    """Write to runtime_state.json::drawdown_state. Fail-soft."""
    try:
        try:
            from runtime_state import write_section  # type: ignore
        except ImportError:
            from shared.runtime_state import write_section  # type: ignore
        write_section("drawdown_state", {
            "alert_level": alert_level,
            "equity_pct_change": equity_pct_change,
            "equity_now": equity_now,
            "equity_base": equity_base,
            "attributed_closed_trades": closed_trades,
            "new_entry_restricted": alert_level in (ALERT_RESTRICT, ALERT_EMERGENCY),
            "updated_at_iso": datetime.now(timezone.utc).isoformat(),
        }, actor="drawdown-escalation")
    except Exception:
        return


def check_unrealized_drawdown(
    *,
    equity_now: float | None,
    equity_base: float | None,
    attributed_closed_trades: int = 0,
    positions: list | None = None,
) -> dict:
    """Main entry. Computes pct change, classifies, escalates, persists.

    Inputs:
    - equity_now: current account equity (paper)
    - equity_base: equity at start of the lookback window (e.g. 3 days ago)
    - attributed_closed_trades: number of closed trades in the window
    - positions: optional list of open position dicts for attribution

    Returns dict with: alert_level, equity_pct_change, attribution[],
    new_entry_restricted, action_enqueued (bool).

    Side effects (all fail-soft):
    - runtime_state.json::drawdown_state updated
    - operator action enqueued on transition
    - audit JSONL line written
    """
    eq_now = _safe_float(equity_now, default=0.0)
    eq_base = _safe_float(equity_base, default=0.0)

    if eq_base <= 0:
        return {
            "alert_level": ALERT_NONE,
            "equity_pct_change": 0.0,
            "attribution": [],
            "new_entry_restricted": False,
            "action_enqueued": False,
            "warning": "EQUITY_BASE_UNAVAILABLE",
        }

    equity_pct_change = ((eq_now - eq_base) / eq_base) * 100.0
    alert_level = _classify_alert_level(equity_pct_change, attributed_closed_trades)

    # Attribution: list of (symbol, unrealized_pl, fraction)
    attribution = []
    if positions:
        try:
            total_unr = sum(_safe_float(p.get("unrealized_pl"), 0.0) for p in positions)
            for p in positions:
                upl = _safe_float(p.get("unrealized_pl"), 0.0)
                attribution.append({
                    "symbol": p.get("symbol"),
                    "unrealized_pl": upl,
                    "share_of_drawdown": (upl / total_unr) if total_unr != 0 else 0.0,
                })
        except Exception:
            pass

    action_enqueued = False
    if alert_level != ALERT_NONE:
        a = _enqueue_drawdown_action(
            alert_level, equity_pct_change, eq_now, eq_base,
            attributed_closed_trades,
        )
        action_enqueued = a is not None

    _persist_state(alert_level, equity_pct_change, eq_now, eq_base,
                    attributed_closed_trades)

    # Audit emit (fail-soft)
    try:
        try:
            from audit import write_audit_event  # type: ignore
        except ImportError:
            from shared.audit import write_audit_event  # type: ignore
        write_audit_event({
            "ts": datetime.now(timezone.utc).isoformat(),
            "decision": "V322_DRAWDOWN_ESCALATION",
            "event_type": "V322_DRAWDOWN_ESCALATION",
            "actor": "drawdown_escalation",
            "alert_level": alert_level,
            "equity_pct_change": equity_pct_change,
            "equity_now": eq_now,
            "equity_base": eq_base,
            "attributed_closed_trades": attributed_closed_trades,
        }, kind="trading")
    except Exception:
        pass

    return {
        "alert_level": alert_level,
        "equity_pct_change": equity_pct_change,
        "attribution": attribution,
        "new_entry_restricted": alert_level in (ALERT_RESTRICT, ALERT_EMERGENCY),
        "action_enqueued": action_enqueued,
    }


__all__ = [
    "DRAWDOWN_NEVER_AUTO_CLOSES",
    "DRAWDOWN_NEVER_RAISES_RISK",
    "DRAWDOWN_ADVISORY_ONLY",
    "ALERT_NONE", "ALERT_WARN", "ALERT_RESTRICT", "ALERT_EMERGENCY",
    "ALL_ALERT_LEVELS",
    "WARN_PCT", "RESTRICT_PCT", "EMERGENCY_PCT",
    "check_unrealized_drawdown",
]
