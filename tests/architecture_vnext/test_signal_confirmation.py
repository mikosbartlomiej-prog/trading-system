"""signal_confirmation — price/volume, dedupe, cooldown, freshness."""
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

import os, sys; sys.path.insert(0, os.path.dirname(__file__)); import _path  # noqa: F401

import signal_confirmation as sc


class TestPriceVolume(unittest.TestCase):
    def test_buy_breakout_passes(self):
        md = {
            "last": 105.0, "sma_20": 100.0, "high_5d": 104.0,
            "volume": 2_000_000, "avg_volume_20": 1_000_000,
        }
        r = sc.confirm_price_volume("AAPL", "buy", md)
        self.assertTrue(r["ok"])

    def test_buy_no_breakout_fails(self):
        md = {
            "last": 98.0, "sma_20": 100.0, "high_5d": 104.0,
            "volume": 2_000_000, "avg_volume_20": 1_000_000,
        }
        r = sc.confirm_price_volume("AAPL", "buy", md)
        self.assertFalse(r["ok"])
        self.assertTrue(any("SMA20" in x or "5d-high" in x for x in r["reasons"]))

    def test_buy_low_volume_fails(self):
        md = {
            "last": 105.0, "sma_20": 100.0, "high_5d": 104.0,
            "volume": 500_000, "avg_volume_20": 1_000_000,
        }
        r = sc.confirm_price_volume("AAPL", "buy", md)
        self.assertFalse(r["ok"])
        self.assertTrue(any("volume" in x.lower() for x in r["reasons"]))

    def test_short_breakdown_passes(self):
        md = {
            "last": 95.0, "sma_20": 100.0, "low_5d": 96.0,
            "volume": 2_000_000, "avg_volume_20": 1_000_000,
        }
        r = sc.confirm_price_volume("AAPL", "sell_short", md)
        self.assertTrue(r["ok"])

    def test_short_above_sma_fails(self):
        md = {
            "last": 102.0, "sma_20": 100.0, "low_5d": 96.0,
            "volume": 2_000_000, "avg_volume_20": 1_000_000,
        }
        r = sc.confirm_price_volume("AAPL", "sell_short", md)
        self.assertFalse(r["ok"])

    def test_market_data_unavailable(self):
        r = sc.confirm_price_volume("AAPL", "buy", None)
        self.assertFalse(r["ok"])

    def test_wide_spread_fails(self):
        md = {
            "last": 100.0, "sma_20": 95.0, "high_5d": 99.0,
            "volume": 2_000_000, "avg_volume_20": 1_000_000,
            "quote": {"bid": 99.0, "ask": 101.0},
        }
        # spread = 2.0/100 = 2% > 1.5% default
        r = sc.confirm_price_volume("AAPL", "buy", md)
        self.assertFalse(r["ok"])
        self.assertTrue(any("spread" in x for x in r["reasons"]))


class TestDedupe(unittest.TestCase):
    def test_fingerprint_stable(self):
        e1 = {"headline": "Trump fires Powell", "source": "reuters",
              "symbol": "SPY", "published_at": "2026-05-14T12:00:00Z"}
        e2 = {"headline": "Trump fires Powell", "source": "reuters",
              "symbol": "SPY", "published_at": "2026-05-14T12:30:00Z"}
        self.assertEqual(sc.event_fingerprint(e1), sc.event_fingerprint(e2))

    def test_duplicate_blocked(self):
        cache = sc.EventCache(path=None)
        e = {"headline": "Iran strike", "source": "twitter", "symbol": "OXY",
             "published_at": "2026-05-14T12:00:00Z"}
        first = sc.dedupe_event(e, cache)
        second = sc.dedupe_event(e, cache)
        self.assertTrue(first["ok"])
        self.assertFalse(second["ok"])
        self.assertTrue(second["was_duplicate"])

    def test_dedupe_persists_to_disk(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            path = f.name
        try:
            os.remove(path)  # let EventCache create it
            cache_a = sc.EventCache(path=path)
            e = {"headline": "X", "source": "Y", "symbol": "Z"}
            sc.dedupe_event(e, cache_a)
            # New cache instance reads from disk
            cache_b = sc.EventCache(path=path)
            r = sc.dedupe_event(e, cache_b)
            self.assertFalse(r["ok"])
        finally:
            if os.path.exists(path):
                os.remove(path)


class TestCooldown(unittest.TestCase):
    def test_cooldown_active(self):
        t = sc.CooldownTracker(path=None)
        t.mark("AAPL", "social")
        r = t.cooldown_ok("AAPL", "social", cooldown_hours=4)
        self.assertFalse(r["ok"])
        self.assertIn("cooldown", r["reason"])

    def test_cooldown_expired(self):
        t = sc.CooldownTracker(path=None)
        t.mark("AAPL", "social", now=time.time() - 5 * 3600)
        r = t.cooldown_ok("AAPL", "social", cooldown_hours=4)
        self.assertTrue(r["ok"])

    def test_cooldown_isolated_per_symbol(self):
        t = sc.CooldownTracker(path=None)
        t.mark("AAPL", "social")
        r = t.cooldown_ok("MSFT", "social", cooldown_hours=4)
        self.assertTrue(r["ok"])


class TestFreshness(unittest.TestCase):
    def test_recent_article_passes(self):
        now = datetime.now(timezone.utc)
        ts = (now - timedelta(hours=1)).isoformat()
        r = sc.article_fresh(ts, max_age_hours=12)
        self.assertTrue(r["ok"])

    def test_stale_article_rejected(self):
        now = datetime.now(timezone.utc)
        ts = (now - timedelta(hours=48)).isoformat()
        r = sc.article_fresh(ts, max_age_hours=12)
        self.assertFalse(r["ok"])
        self.assertIn("old", r["reason"])

    def test_unparseable_rejected(self):
        r = sc.article_fresh("yesterday", max_age_hours=12)
        self.assertFalse(r["ok"])

    def test_missing_published_at_rejected(self):
        r = sc.article_fresh(None, max_age_hours=12)
        self.assertFalse(r["ok"])

    def test_future_timestamp_rejected(self):
        now = datetime.now(timezone.utc)
        future = (now + timedelta(hours=1)).isoformat()
        r = sc.article_fresh(future, max_age_hours=12)
        self.assertFalse(r["ok"])


class TestIntegration(unittest.TestCase):
    def test_full_pipeline_blocks_when_unconfirmed(self):
        event = {"headline": "Random rumor", "source": "tweet",
                 "symbol": "AAPL",
                 "published_at": datetime.now(timezone.utc).isoformat()}
        # No price/volume confirmation
        md = {"last": 95.0, "sma_20": 100.0, "high_5d": 104.0,
              "volume": 500_000, "avg_volume_20": 1_000_000}
        r = sc.confirm_event_signal(
            event=event, side="buy", market_data=md,
            event_cache=None, cooldown=None,
            cooldown_hours=4, max_article_age_hours=12,
        )
        self.assertFalse(r["ok"])
        self.assertIn("price_volume", r["blocked_by"])

    def test_full_pipeline_passes_when_confirmed(self):
        event = {"headline": "Big news", "source": "reuters",
                 "symbol": "AAPL",
                 "published_at": datetime.now(timezone.utc).isoformat()}
        md = {"last": 105.0, "sma_20": 100.0, "high_5d": 104.0,
              "volume": 2_000_000, "avg_volume_20": 1_000_000}
        r = sc.confirm_event_signal(
            event=event, side="buy", market_data=md,
            event_cache=None, cooldown=None,
            cooldown_hours=4, max_article_age_hours=12,
        )
        self.assertTrue(r["ok"])


if __name__ == "__main__":
    unittest.main()
