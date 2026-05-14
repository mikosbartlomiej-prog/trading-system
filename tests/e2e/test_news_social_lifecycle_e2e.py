"""E2E: news/social events must pass signal_confirmation before any order."""

import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import conftest  # noqa: F401

import unittest
from datetime import datetime, timedelta, timezone

import signal_confirmation as sc
from tools.e2e_system_test_agent.fixtures import (
    FakeNewsFeed, FakeSocialFeed, FakeMarketData,
)


class TestNewsConfirmation(unittest.TestCase):
    def setUp(self):
        self.news = FakeNewsFeed()
        self.market = FakeMarketData()

    def test_fresh_news_with_price_volume_passes(self):
        ev = self.news.add_fresh(symbol="XOM",
                                  headline="OPEC announces production cut",
                                  source="reuters", minutes_ago=15)
        md = {
            "last": 105.0, "sma_20": 100.0, "high_5d": 104.0,
            "volume": 2_500_000, "avg_volume_20": 1_000_000,
        }
        r = sc.confirm_event_signal(
            event={**ev, "symbol": "XOM"}, side="buy", market_data=md,
            event_cache=None, cooldown=None,
            cooldown_hours=4, max_article_age_hours=12,
        )
        self.assertTrue(r["ok"])

    def test_fresh_news_without_price_confirmation_blocked(self):
        ev = self.news.add_fresh(symbol="XOM", headline="rumor",
                                  source="newsapi", minutes_ago=15)
        md = {
            "last": 95.0, "sma_20": 100.0, "high_5d": 104.0,
            "volume": 500_000, "avg_volume_20": 1_000_000,
        }
        r = sc.confirm_event_signal(
            event={**ev, "symbol": "XOM"}, side="buy", market_data=md,
            event_cache=None, cooldown=None,
            cooldown_hours=4, max_article_age_hours=12,
        )
        self.assertFalse(r["ok"])
        self.assertIn("price_volume", r["blocked_by"])

    def test_stale_news_rejected(self):
        ev = self.news.add_stale(symbol="XOM", headline="old news",
                                   hours_ago=36)
        md = {"last": 105, "sma_20": 100, "high_5d": 104,
              "volume": 2_000_000, "avg_volume_20": 1_000_000}
        r = sc.confirm_event_signal(
            event={**ev, "symbol": "XOM"}, side="buy", market_data=md,
            event_cache=None, cooldown=None,
            cooldown_hours=4, max_article_age_hours=12,
        )
        self.assertFalse(r["ok"])
        self.assertIn("freshness", r["blocked_by"])

    def test_duplicate_event_rejected(self):
        ev = self.news.add_fresh(symbol="XOM", headline="X", source="r")
        md = {"last": 105, "sma_20": 100, "high_5d": 104,
              "volume": 2_000_000, "avg_volume_20": 1_000_000}
        cache = sc.EventCache(path=None)
        r1 = sc.confirm_event_signal(
            event={**ev, "symbol": "XOM"}, side="buy", market_data=md,
            event_cache=cache, cooldown=None,
            cooldown_hours=4, max_article_age_hours=12,
        )
        r2 = sc.confirm_event_signal(
            event={**ev, "symbol": "XOM"}, side="buy", market_data=md,
            event_cache=cache, cooldown=None,
            cooldown_hours=4, max_article_age_hours=12,
        )
        self.assertTrue(r1["ok"])
        self.assertFalse(r2["ok"])
        self.assertIn("dedupe", r2["blocked_by"])


class TestSocialConfirmation(unittest.TestCase):
    def test_reddit_spike_without_price_confirmation_blocked(self):
        social = FakeSocialFeed()
        spike = social.add_reddit_spike(symbol="NVDA", mentions=80, skew=0.5)
        md = {"last": 95.0, "sma_20": 100.0, "high_5d": 104.0,
              "volume": 500_000, "avg_volume_20": 1_000_000}
        r = sc.confirm_event_signal(
            event={"symbol": "NVDA", "headline": "reddit spike",
                   "source": "reddit",
                   "published_at": spike["published_at"]},
            side="buy", market_data=md, event_cache=None, cooldown=None,
            cooldown_hours=4, max_article_age_hours=12,
        )
        self.assertFalse(r["ok"])
        self.assertIn("price_volume", r["blocked_by"])

    def test_cooldown_blocks_repeat(self):
        cooldown = sc.CooldownTracker(path=None)
        cooldown.mark("NVDA", "social")
        r = cooldown.cooldown_ok("NVDA", "social", cooldown_hours=4)
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
