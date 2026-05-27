"""v3.10 — signal_confirmation intraday classification (Phase C)."""

import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(__file__))
import _path  # noqa: F401

import unittest
from datetime import datetime, timezone, timedelta

from signal_confirmation import (
    classify_news_signal_intraday, EventCache, CooldownTracker,
)
from risk_classification import RiskVerdict


def _event(sym="AAPL", age_hours=1.0):
    ts = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    return {
        "symbol": sym,
        "published_at": ts,
        "headline": f"Breaking news about {sym}",
        "source": "test",
    }


def _md_confirmed(side="BUY"):
    """Market data that should pass price_volume confirmation."""
    return {
        "last": 200.0,
        "sma_20": 195.0,
        "volume": 5_000_000, "avg_volume_20": 3_000_000,
        "high_5d": 199.0, "low_5d": 190.0,
        "quote": {"bid": 199.95, "ask": 200.05},
    }


def _md_unconfirmed():
    """Market data that FAILS price_volume confirmation."""
    return {
        "last": 200.0,
        "sma_20": 205.0,  # last < SMA → no long confirm
        "volume": 1_000_000, "avg_volume_20": 3_000_000,  # vol < avg
        "high_5d": 210.0, "low_5d": 195.0,  # last < high_5d
        "quote": {"bid": 198.0, "ask": 202.0},  # wide spread
    }


class TestIntradayClassification(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cache = EventCache(path=os.path.join(self.tmp, "events.json"))
        self.cool = CooldownTracker(path=os.path.join(self.tmp, "cool.json"))

    def test_full_confirmation_returns_allow(self):
        d = classify_news_signal_intraday(
            event=_event(), side="BUY", market_data=_md_confirmed("BUY"),
            event_cache=self.cache, cooldown=self.cool,
            signal_strength=0.6,
        )
        self.assertEqual(d.verdict, RiskVerdict.ALLOW)

    def test_duplicate_event_blocks(self):
        ev = _event()
        # First call records the event
        classify_news_signal_intraday(
            event=ev, side="BUY", market_data=_md_confirmed(),
            event_cache=self.cache, cooldown=self.cool,
            signal_strength=0.8,
        )
        # Second call (same fingerprint) → BLOCK
        d = classify_news_signal_intraday(
            event=ev, side="BUY", market_data=_md_confirmed(),
            event_cache=self.cache, cooldown=self.cool,
            signal_strength=0.8,
        )
        self.assertEqual(d.verdict, RiskVerdict.BLOCK)
        self.assertIn("duplicate", d.reason.lower())

    def test_future_timestamp_blocks(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        ev = {"symbol": "FUT", "published_at": future, "headline": "future"}
        d = classify_news_signal_intraday(
            event=ev, side="BUY", market_data=_md_confirmed(),
            event_cache=self.cache, cooldown=self.cool,
            signal_strength=0.9,
        )
        self.assertEqual(d.verdict, RiskVerdict.BLOCK)
        self.assertIn("future", d.reason.lower())

    def test_very_stale_blocks(self):
        ev = _event(age_hours=200)  # 200h old vs 6h*4=24h threshold
        d = classify_news_signal_intraday(
            event=ev, side="BUY", market_data=_md_confirmed(),
            event_cache=self.cache, cooldown=self.cool,
            signal_strength=0.8,
        )
        self.assertEqual(d.verdict, RiskVerdict.BLOCK)
        self.assertIn("stale", d.reason.lower())

    def test_strong_signal_partial_confirm_downsize(self):
        d = classify_news_signal_intraday(
            event=_event(), side="BUY", market_data=_md_unconfirmed(),
            event_cache=self.cache, cooldown=self.cool,
            signal_strength=0.85,   # strong
        )
        self.assertEqual(d.verdict, RiskVerdict.DOWNSIZE)
        self.assertEqual(d.size_multiplier, 0.5)

    def test_moderate_signal_partial_confirm_smaller_downsize(self):
        d = classify_news_signal_intraday(
            event=_event(), side="BUY", market_data=_md_unconfirmed(),
            event_cache=self.cache, cooldown=self.cool,
            signal_strength=0.5,
        )
        self.assertEqual(d.verdict, RiskVerdict.DOWNSIZE)
        self.assertEqual(d.size_multiplier, 0.3)

    def test_weak_signal_no_confirm_alert_only(self):
        d = classify_news_signal_intraday(
            event=_event(), side="BUY", market_data=_md_unconfirmed(),
            event_cache=self.cache, cooldown=self.cool,
            signal_strength=0.2,  # weak
        )
        self.assertEqual(d.verdict, RiskVerdict.ALERT_ONLY)
        self.assertIn("weak", d.reason.lower())

    def test_cooldown_blocks(self):
        # First signal stamps cooldown by going through whole path
        ev = _event(sym="MSFT")
        # Manually stamp cooldown
        self.cool.mark("MSFT", "news")
        d = classify_news_signal_intraday(
            event=ev, side="BUY", market_data=_md_confirmed(),
            event_cache=self.cache, cooldown=self.cool,
            signal_strength=0.7, cooldown_hours=4.0,
        )
        self.assertEqual(d.verdict, RiskVerdict.BLOCK)
        self.assertIn("cooldown", d.reason.lower())


if __name__ == "__main__":
    unittest.main()
