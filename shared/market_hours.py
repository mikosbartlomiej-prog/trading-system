"""
shared/market_hours.py — US equity market hours helper.

Used by 24/7 monitors (defense, twitter, geo) to detect when stock
signals fire pre-market / after-hours / weekend and avoid trying to
place orders that Alpaca will reject. Crypto-monitor doesn't need
this (crypto trades 24/7).

API:
  is_us_market_open() -> (open: bool, reason: str)
  minutes_to_next_open() -> int (negative if market is currently open)

Reason strings:
  "open"        — regular hours 09:30-16:00 ET, weekday
  "pre_market"  — 04:00-09:30 ET, weekday (extended-hours capable)
  "after_hours" — 16:00-20:00 ET, weekday (extended-hours capable)
  "closed"      — 20:00-04:00 ET, weekday (Alpaca won't accept)
  "weekend"     — Saturday or Sunday
  "holiday"     — US market holiday (hardcoded common list)

Holidays list is conservative — only major US closures. For exact
schedule consult NYSE calendar; this helper aims to prevent the
most common pre-market false-rejection emails, not to be authoritative.
"""

from datetime import datetime, time, date
from zoneinfo import ZoneInfo


_ET = ZoneInfo("America/New_York")

# Regular session
_OPEN_HOUR, _OPEN_MIN   = 9, 30
_CLOSE_HOUR, _CLOSE_MIN = 16, 0
# Extended hours window (Alpaca supports with extended_hours=true flag,
# but our code doesn't currently use it — treated as "closed" for now).
_PREMKT_OPEN_HOUR  = 4
_AFTER_CLOSE_HOUR  = 20

# Conservative hardcoded US market holidays for 2026.
# Source: NYSE published calendar. Update annually.
_HOLIDAYS_2026 = {
    date(2026, 1, 1),    # New Year's Day
    date(2026, 1, 19),   # MLK Day
    date(2026, 2, 16),   # Presidents' Day
    date(2026, 4, 3),    # Good Friday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 6, 19),   # Juneteenth
    date(2026, 7, 3),    # Independence Day (observed)
    date(2026, 9, 7),    # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas
}


def is_us_market_open(now=None) -> tuple[bool, str]:
    """
    Returns (open, reason). `open` is True only during regular hours.
    `reason` is one of: open, pre_market, after_hours, closed, weekend, holiday.

    `now` optional — pass datetime for testing; defaults to current ET time.
    """
    if now is None:
        now = datetime.now(_ET)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=_ET)
    else:
        now = now.astimezone(_ET)

    today = now.date()
    weekday = now.weekday()      # Mon=0, Sun=6
    t = now.time()

    if weekday >= 5:
        return False, "weekend"

    if today in _HOLIDAYS_2026:
        return False, "holiday"

    open_t  = time(_OPEN_HOUR, _OPEN_MIN)
    close_t = time(_CLOSE_HOUR, _CLOSE_MIN)
    premkt_t = time(_PREMKT_OPEN_HOUR, 0)
    aftclose_t = time(_AFTER_CLOSE_HOUR, 0)

    if open_t <= t < close_t:
        return True, "open"
    if premkt_t <= t < open_t:
        return False, "pre_market"
    if close_t <= t < aftclose_t:
        return False, "after_hours"
    return False, "closed"


def minutes_to_next_open(now=None) -> int:
    """
    Minutes until next regular-session open. Negative if currently open
    (returns time since open). Returns large positive number on weekend.

    Useful for monitors to log "ITA signal will fire in X min when
    market opens".
    """
    if now is None:
        now = datetime.now(_ET)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=_ET)
    else:
        now = now.astimezone(_ET)

    open_t = time(_OPEN_HOUR, _OPEN_MIN)
    open_today = now.replace(hour=_OPEN_HOUR, minute=_OPEN_MIN, second=0, microsecond=0)

    is_open, reason = is_us_market_open(now)
    if is_open:
        # Negative: how long market has been open
        return int(-(now - open_today).total_seconds() / 60)

    # Find next open: skip forward through non-business days/holidays
    target = now
    if target.time() >= open_t:
        # Past today's open — go to tomorrow
        from datetime import timedelta
        target = (target + timedelta(days=1)).replace(
            hour=_OPEN_HOUR, minute=_OPEN_MIN, second=0, microsecond=0
        )
    else:
        target = target.replace(hour=_OPEN_HOUR, minute=_OPEN_MIN, second=0, microsecond=0)

    # Skip weekends + holidays
    from datetime import timedelta
    while target.weekday() >= 5 or target.date() in _HOLIDAYS_2026:
        target = target + timedelta(days=1)
        target = target.replace(hour=_OPEN_HOUR, minute=_OPEN_MIN, second=0, microsecond=0)

    return int((target - now).total_seconds() / 60)
