"""Deterministic clock + market hours + cooldown windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class FakeClock:
    now: datetime = datetime(2026, 5, 15, 14, 0, 0, tzinfo=timezone.utc)  # Fri 14:00 UTC
    market_open: bool = True

    def advance(self, *, seconds: int = 0, minutes: int = 0, hours: int = 0,
                days: int = 0) -> "FakeClock":
        self.now = self.now + timedelta(seconds=seconds, minutes=minutes,
                                        hours=hours, days=days)
        return self

    def set_to_market_open(self):
        self.now = self.now.replace(hour=13, minute=30, second=0)
        self.market_open = True

    def set_to_market_close(self):
        self.now = self.now.replace(hour=20, minute=0, second=0)
        self.market_open = True

    def set_to_weekend(self):
        # Move to Saturday
        days_ahead = (5 - self.now.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        self.now = self.now + timedelta(days=days_ahead)
        self.market_open = False

    def utc_iso(self) -> str:
        return self.now.isoformat()
