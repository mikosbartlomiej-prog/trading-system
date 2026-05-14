"""Reddit / Bluesky-style social-feed fakes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class FakeSocialFeed:
    items: list[dict] = field(default_factory=list)

    def add_reddit_spike(self, *, symbol: str, mentions: int = 50,
                          skew: float = 0.6,
                          credibility: int = 55) -> dict:
        item = {
            "kind":           "reddit",
            "symbol":         symbol,
            "mentions_24h":   mentions,
            "sentiment_skew": skew,
            "credibility":    credibility,
            "published_at":   datetime.now(timezone.utc).isoformat(),
        }
        self.items.append(item)
        return item

    def add_bluesky_post(self, *, handle: str, symbol: str, text: str,
                         credibility: int = 70) -> dict:
        item = {
            "kind":          "bluesky",
            "handle":        handle,
            "symbol":        symbol,
            "text":          text,
            "credibility":   credibility,
            "published_at":  datetime.now(timezone.utc).isoformat(),
        }
        self.items.append(item)
        return item

    def all(self) -> list[dict]:
        return list(self.items)

    def clear(self) -> None:
        self.items.clear()
