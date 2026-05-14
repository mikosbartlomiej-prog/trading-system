"""News feed fixtures — fresh / stale / duplicate / unconfirmed."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class FakeNewsFeed:
    items: list[dict] = field(default_factory=list)

    def add_fresh(self, *, symbol: str, headline: str, source: str = "reuters",
                   minutes_ago: int = 30) -> dict:
        ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
        item = {"symbol": symbol, "headline": headline,
                 "source": source, "published_at": ts, "credibility": 75}
        self.items.append(item)
        return item

    def add_stale(self, *, symbol: str, headline: str, hours_ago: int = 36) -> dict:
        ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
        item = {"symbol": symbol, "headline": headline,
                 "source": "newsapi", "published_at": ts, "credibility": 60}
        self.items.append(item)
        return item

    def add_duplicate(self, original: dict, *, minutes_later: int = 10) -> dict:
        copy = dict(original)
        copy["published_at"] = (datetime.fromisoformat(original["published_at"])
                                + timedelta(minutes=minutes_later)).isoformat()
        self.items.append(copy)
        return copy

    def all(self) -> list[dict]:
        return list(self.items)

    def clear(self) -> None:
        self.items.clear()
