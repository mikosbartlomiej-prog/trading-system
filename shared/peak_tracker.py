"""
shared/peak_tracker.py — legacy compatibility shim for IntradayProfitGovernor.

Built 2026-05-13 in response to 2026-05-12 disaster:
  +$3,173 peak P&L at 17:56 UTC → -$184 by 22:18 UTC.
  Full reversal of intraday gains; ZERO reaction from system.

The original v3.3 implementation persisted state into
`learning-loop/state.json::daily_peak`, but the 5-minute workflows that
need this data (exit-monitor, price-monitor) cannot commit state.json
under the architecture vNext rule C (`contents: read`). In production
the writes silently disappeared and the cascade never armed.

Refactored 2026-05-14 (this iteration):
  - State storage moves to `learning-loop/runtime_state.json` via
    shared/runtime_state.py (custodied by exit-monitor with
    `contents: write` + a tiny post-step git push of that single file).
  - Logic is owned by shared/intraday_governor.py — a 7-state FSM with
    explicit DEFEND_DAY / RED_DAY_AFTER_GREEN tiers, position-level MFE
    harvest, profit floor, dynamic gross-exposure cap, and audit events.
  - This file becomes a thin shim that preserves the old public API
    (update_peak, get_peak, should_profit_lock, harvest_threshold_usd,
    mark_alert_sent, alert_already_sent_today, summarize, plus VERDICT_*
    constants). Existing callers in exit-monitor + tests continue to
    work unchanged; new code should consume intraday_governor directly.

Legacy 3-verdict mapping ← new 7-state FSM:
  governor STATE_NEW_DAY                            → VERDICT_NEW_DAY
  governor STATE_FLAT / GREEN / STRONG_GREEN        → VERDICT_NORMAL
  governor STATE_GIVEBACK_WARN                      → VERDICT_WARN
  governor STATE_PROFIT_LOCK / DEFEND_DAY / RED_DAY → VERDICT_PROFIT_LOCK
"""

from __future__ import annotations

from typing import Any

try:
    from intraday_governor import (
        update as _gov_update,
        get_snapshot as _gov_get_snapshot,
        mark_alert_sent as _gov_mark_alert_sent,
        alert_already_sent as _gov_alert_already_sent,
        summarize as _gov_summarize,
        STATE_NEW_DAY, STATE_FLAT, STATE_GREEN, STATE_STRONG_GREEN,
        STATE_GIVEBACK_WARN, STATE_PROFIT_LOCK, STATE_DEFEND_DAY,
        STATE_RED_DAY_AFTER_GREEN,
    )
except ImportError:                                              # pragma: no cover
    from shared.intraday_governor import (                       # type: ignore
        update as _gov_update,
        get_snapshot as _gov_get_snapshot,
        mark_alert_sent as _gov_mark_alert_sent,
        alert_already_sent as _gov_alert_already_sent,
        summarize as _gov_summarize,
        STATE_NEW_DAY, STATE_FLAT, STATE_GREEN, STATE_STRONG_GREEN,
        STATE_GIVEBACK_WARN, STATE_PROFIT_LOCK, STATE_DEFEND_DAY,
        STATE_RED_DAY_AFTER_GREEN,
    )


# ─── Legacy constants (kept for back-compat with exit-monitor + tests) ───────

MIN_PEAK_FOR_LOCK_USD   = 1000.0
WARN_RETRACE_PCT        = 0.25   # was 0.30 — synced to GIVEBACK_WARN threshold
PROFIT_LOCK_RETRACE_PCT = 0.35   # was 0.50 — synced to PROFIT_LOCK threshold
HARVEST_MULTIPLIER      = 0.70

VERDICT_NORMAL      = "NORMAL"
VERDICT_WARN        = "WARN"
VERDICT_PROFIT_LOCK = "PROFIT_LOCK"
VERDICT_NEW_DAY     = "NEW_DAY"

# Tests patch this attribute to redirect persistence. We forward to the
# governor's runtime_state file; tests that need an isolated path should
# monkeypatch shared.runtime_state.RUNTIME_STATE_PATH instead.
import os as _os
_REPO_ROOT  = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
_STATE_PATH = _os.path.join(_REPO_ROOT, "learning-loop", "state.json")  # legacy hint


# ─── Internal mapping ────────────────────────────────────────────────────────

def _verdict_from_state(state: str) -> str:
    if state in (STATE_PROFIT_LOCK, STATE_DEFEND_DAY, STATE_RED_DAY_AFTER_GREEN):
        return VERDICT_PROFIT_LOCK
    if state == STATE_GIVEBACK_WARN:
        return VERDICT_WARN
    if state == STATE_NEW_DAY:
        return VERDICT_NEW_DAY
    return VERDICT_NORMAL


def _snap_to_legacy_dict(snap) -> dict:
    """Translate IntradaySnapshot → legacy daily_peak dict shape."""
    return {
        "date":              snap.date,
        "peak_pl_usd":       snap.intraday_peak_pnl,
        "peak_pl_pct":       snap.intraday_peak_pnl_pct,
        "peak_at":           snap.peak_at,
        "peak_equity":       snap.intraday_peak_equity,
        "current_pl_usd":    snap.current_intraday_pnl,
        "current_equity":    snap.current_equity,
        "retrace_from_peak": snap.giveback_pct_of_peak,
        "verdict":           _verdict_from_state(snap.pnl_state),
        "verdict_at":        snap.last_update_at,
        "alerts_sent":       dict(snap.alerts_sent or {}),
        # Bonus: surface the richer FSM state for new callers without
        # breaking old ones (they only read the keys above).
        "pnl_state":         snap.pnl_state,
        "max_gross_target":  snap.max_gross_target,
        "profit_floor_usd":  snap.profit_floor_usd,
        "block_new_entries": snap.block_new_entries,
    }


# ─── Public API (unchanged surface) ──────────────────────────────────────────

def update_peak(account: dict | None = None) -> dict:
    """Update the intraday governor + return legacy daily_peak dict."""
    snap = _gov_update(account=account)
    return _snap_to_legacy_dict(snap)


def get_peak() -> dict:
    """Read-only legacy daily_peak dict."""
    snap = _gov_get_snapshot()
    return _snap_to_legacy_dict(snap)


def should_profit_lock() -> tuple[bool, dict]:
    """True iff legacy verdict == PROFIT_LOCK (includes DEFEND_DAY + RED_DAY)."""
    snap = _gov_get_snapshot()
    legacy = _snap_to_legacy_dict(snap)
    return legacy["verdict"] == VERDICT_PROFIT_LOCK, legacy


def harvest_threshold_usd() -> float | None:
    """Peak × 0.70 when in profit-lock cascade, else None."""
    snap = _gov_get_snapshot()
    if _verdict_from_state(snap.pnl_state) != VERDICT_PROFIT_LOCK:
        return None
    return float(snap.intraday_peak_pnl) * HARVEST_MULTIPLIER


def mark_alert_sent(level: str) -> None:
    _gov_mark_alert_sent(level)


def alert_already_sent_today(level: str) -> bool:
    return _gov_alert_already_sent(level)


def summarize(peak: dict[str, Any] | None = None) -> str:
    """One-line log summary. `peak` arg accepted for back-compat; ignored."""
    return _gov_summarize()
