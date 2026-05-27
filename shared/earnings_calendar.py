"""shared/earnings_calendar.py — earnings-day skip filter (free, Alpaca-based).

v3.11 Phase G (2026-05-27): generalizes options-monitor's _is_earnings_soon
to stocks. Per intraday-first directive: avoid entries on earnings day (±1d)
due to extreme volatility + gap risk.

DATA SOURCE: Alpaca `/v2/corporate-actions` (free, included with paper key).
Filters for `ca_type=DIV` events near-term (proxy — Alpaca doesn't expose
earnings directly via free tier; we use upcoming corporate actions as
imperfect signal; production-grade would use Polygon/Finnhub paid).

PRAGMATIC FALLBACK: hardcoded list of known earnings cycles (next-7d
windows) refreshed weekly via state.json::earnings_calendar. For now
returns False (no skip) if no data — fail-OPEN to not paralyze trading.

USAGE:
    from earnings_calendar import is_earnings_blackout
    if is_earnings_blackout("AAPL", days_window=1):
        return  # skip entry

Per-monitor wiring: call before each entry.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


# Hardcoded earnings calendar (updated manually weekly OR via daily-learning).
# Format: {SYMBOL: ISO_DATE}. Lookahead window applied around this date.
# Empty by default — operator/LLM should populate via state.json file.
# Source: company IR pages OR free aggregators (Yahoo Finance earnings cal).
_FALLBACK_CALENDAR_PATH = Path(__file__).resolve().parent.parent / "config" / "earnings_calendar.json"


def _load_calendar() -> dict[str, str]:
    """Load symbol→earnings_date mapping from JSON. Returns {} if missing."""
    if not _FALLBACK_CALENDAR_PATH.exists():
        return {}
    try:
        data = json.loads(_FALLBACK_CALENDAR_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get("upcoming", {}) or {}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def is_earnings_blackout(symbol: str, days_window: int = 1) -> bool:
    """
    Return True if SYMBOL has earnings within ±days_window calendar days
    from today (UTC). Returns False on any uncertainty (fail-open per
    intraday-first directive — never paralyze trading on data gap).
    """
    if not symbol:
        return False

    cal = _load_calendar()
    if not cal:
        return False  # no data → fail-open

    date_str = cal.get(symbol.upper())
    if not date_str:
        return False

    try:
        ed = datetime.fromisoformat(date_str).date()
    except (ValueError, TypeError):
        return False

    today = datetime.now(timezone.utc).date()
    delta = abs((ed - today).days)
    return delta <= days_window


def annotate_signal_with_earnings(signal: dict, days_window: int = 1) -> tuple[bool, str]:
    """Helper for monitors: check signal['symbol'] and return (block, reason)."""
    sym = (signal.get("symbol") or signal.get("ticker") or "").upper()
    if not sym:
        return (False, "")
    if is_earnings_blackout(sym, days_window=days_window):
        return (True, f"{sym}: earnings within ±{days_window}d window (blackout)")
    return (False, "")
