"""
shared/peak_tracker.py — intraday daily P&L peak + retrace detector.

Built 2026-05-13 in response to 2026-05-12 disaster:
  +$3,173 peak P&L at 17:56 UTC → -$184 by 22:18 UTC.
  Full reversal of intraday gains; ZERO reaction from system.
  Winners (PUTs +47% to +93%) never had TPs hit because static
  TP=entry*1.80 was too far; trailing stop was disabled.

This module fixes the blind spot:
  1. Every cron call updates state.daily_peak_pl with max(prev, current)
  2. Computes retrace_from_peak_pct = (peak - current) / peak
  3. Exposes "profit-lock cascade" verdict:
       NORMAL              — peak < $1000 OR retrace < 30%
       WARN                — peak >= $1000 AND retrace in [30%, 50%)
       PROFIT_LOCK         — peak >= $1000 AND retrace >= 50%
  4. Auto-resets at UTC midnight (new trading day = fresh peak).

Consumers:
  - exit-monitor: on PROFIT_LOCK, replaces standard TP/SL evaluation
    with "close winners at peak * 0.70" mode (aggressive harvest).
  - notify.py: WARN/PROFIT_LOCK trigger email alerts so operator
    sees the regime change in real time.

State lives in `learning-loop/state.json::daily_peak`:
  {
    "date":               "YYYY-MM-DD",
    "peak_pl_usd":        3173.48,
    "peak_pl_pct":        0.0326,
    "peak_at":            "2026-05-12T17:56:00Z",
    "peak_equity":        100496.07,
    "current_pl_usd":     -186.40,
    "current_equity":     97136.00,
    "retrace_from_peak":  1.06,
    "verdict":            "PROFIT_LOCK",
    "verdict_at":         "2026-05-13T08:12:00Z",
    "alerts_sent": {"WARN": "...", "PROFIT_LOCK": "..."}   # dedup
  }
"""

import json
import os
from datetime import datetime, timezone
from typing import Any

_REPO_ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_STATE_PATH = os.path.join(_REPO_ROOT, "learning-loop", "state.json")

# Thresholds (mirror docs/STRATEGY.md). Stored as constants — promote to
# config/aggressive_profile.json if operator wants per-regime tuning.
MIN_PEAK_FOR_LOCK_USD   = 1000.0   # Below this, retrace is just noise — don't trigger
WARN_RETRACE_PCT        = 0.30     # 30% retrace from peak → WARN
PROFIT_LOCK_RETRACE_PCT = 0.50     # 50% retrace from peak → PROFIT_LOCK
HARVEST_MULTIPLIER      = 0.70     # On PROFIT_LOCK, close winners at peak × this

VERDICT_NORMAL      = "NORMAL"
VERDICT_WARN        = "WARN"
VERDICT_PROFIT_LOCK = "PROFIT_LOCK"
VERDICT_NEW_DAY     = "NEW_DAY"   # First call of a new UTC day


def _load_state() -> dict:
    try:
        with open(_STATE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    try:
        with open(_STATE_PATH, "w") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"  peak_tracker: save state failed: {e}")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def update_peak(account: dict | None = None) -> dict:
    """
    Update the daily peak tracker from current account state.

    `account` optional — if None, fetches via shared.risk_guards.get_account_status.
    For tests, pass an explicit dict {equity, last_equity, daily_pl_pct}.

    Returns the updated daily_peak dict (with `verdict` field set).
    """
    if account is None:
        try:
            from risk_guards import get_account_status
        except ImportError:
            from shared.risk_guards import get_account_status
        account = get_account_status() or {}

    equity      = float(account.get("equity", 0) or 0)
    last_equity = float(account.get("last_equity", 0) or 0)
    daily_pl    = equity - last_equity if last_equity > 0 else 0.0
    daily_pl_pct = (daily_pl / last_equity) if last_equity > 0 else 0.0
    now_iso = _utcnow_iso()
    today   = _today_iso()

    state = _load_state()
    peak = state.get("daily_peak") or {}

    # New trading day → reset peak
    if peak.get("date") != today:
        peak = {
            "date":              today,
            "peak_pl_usd":       max(0.0, daily_pl),   # don't track negative as "peak"
            "peak_pl_pct":       max(0.0, daily_pl_pct),
            "peak_at":           now_iso,
            "peak_equity":       equity,
            "current_pl_usd":    daily_pl,
            "current_equity":    equity,
            "retrace_from_peak": 0.0,
            "verdict":           VERDICT_NEW_DAY,
            "verdict_at":        now_iso,
            "alerts_sent":       {},
        }
        state["daily_peak"] = peak
        _save_state(state)
        return peak

    # Update peak if current is higher
    if daily_pl > peak.get("peak_pl_usd", 0):
        peak["peak_pl_usd"]   = daily_pl
        peak["peak_pl_pct"]   = daily_pl_pct
        peak["peak_at"]       = now_iso
        peak["peak_equity"]   = equity

    # Always update current
    peak["current_pl_usd"]  = daily_pl
    peak["current_equity"]  = equity

    # Compute retrace from peak
    pk = peak.get("peak_pl_usd", 0)
    if pk > 0:
        peak["retrace_from_peak"] = max(0.0, (pk - daily_pl) / pk)
    else:
        peak["retrace_from_peak"] = 0.0

    # Verdict
    peak["verdict"]    = _compute_verdict(peak)
    peak["verdict_at"] = now_iso

    state["daily_peak"] = peak
    _save_state(state)
    return peak


def _compute_verdict(peak: dict) -> str:
    pk      = peak.get("peak_pl_usd", 0)
    retrace = peak.get("retrace_from_peak", 0)
    if pk < MIN_PEAK_FOR_LOCK_USD:
        return VERDICT_NORMAL
    if retrace >= PROFIT_LOCK_RETRACE_PCT:
        return VERDICT_PROFIT_LOCK
    if retrace >= WARN_RETRACE_PCT:
        return VERDICT_WARN
    return VERDICT_NORMAL


def get_peak() -> dict:
    """Read-only access; does not fetch account. Returns {} if no state."""
    return _load_state().get("daily_peak") or {}


def should_profit_lock() -> tuple[bool, dict]:
    """
    Convenience: True iff verdict == PROFIT_LOCK. Returns (bool, full_peak_dict).
    Caller can use peak dict to compute harvest_threshold = peak_pl_usd * HARVEST_MULTIPLIER.
    """
    p = get_peak()
    return p.get("verdict") == VERDICT_PROFIT_LOCK, p


def harvest_threshold_usd() -> float | None:
    """
    Threshold in $ from which exit-monitor's profit-lock cascade starts
    aggressively closing winning options. Returns None if not in lock mode.
    """
    p = get_peak()
    if p.get("verdict") != VERDICT_PROFIT_LOCK:
        return None
    return float(p.get("peak_pl_usd", 0)) * HARVEST_MULTIPLIER


def mark_alert_sent(level: str) -> None:
    """Persist that an alert at `level` (WARN / PROFIT_LOCK) was emailed, for dedup."""
    state = _load_state()
    peak = state.get("daily_peak") or {}
    alerts = peak.get("alerts_sent") or {}
    alerts[level] = _utcnow_iso()
    peak["alerts_sent"] = alerts
    state["daily_peak"] = peak
    _save_state(state)


def alert_already_sent_today(level: str) -> bool:
    """True iff we already emailed at this level today."""
    p = get_peak()
    return level in (p.get("alerts_sent") or {})


def summarize(p: dict) -> str:
    """One-line human summary for logs."""
    if not p:
        return "(no peak data yet today)"
    return (
        f"peak=${p.get('peak_pl_usd',0):+.0f} at {p.get('peak_at','?')[-9:-1]}  "
        f"current=${p.get('current_pl_usd',0):+.0f}  "
        f"retrace={p.get('retrace_from_peak',0):.1%}  "
        f"verdict={p.get('verdict','?')}"
    )
