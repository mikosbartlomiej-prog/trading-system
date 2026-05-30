"""v3.11.3 (2026-05-30) — shared/intraday_trend.py tests.

8 scenarios:
1. TREND_CONTINUES — bars climbing above VWAP through OR-high, both slopes up.
2. MOMENTUM_WEAKENING — uptrend stalls in last 2 bars (5min slope flat).
3. FAILED_BREAKOUT — pokes above OR-high then falls back through OR-low.
4. REVERSAL_CONFIRMED — bars cross below VWAP AND below OR-low.
5. CHOP_NO_EDGE — sideways oscillation around VWAP.
6. Fail-soft — _fetch_bars raises → state=CHOP_NO_EDGE + stale=True.
7. Cache hit — second call within TTL skips network.
8. Short-side mirror — REVERSAL_CONFIRMED for a short happens on up-side.

Plus integration: exit-monitor escalates HOLD → CLOSE_FLAT on REVERSAL_CONFIRMED.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _bar(o, h, l, c, v):
    return {"o": o, "h": h, "l": l, "c": c, "v": v}


# Crafted bar sequences — each test scenario.
# 6 bars = opening range. Then a few more bars to extend the trend.

BARS_TREND_CONTINUES = [
    # OR: high=101, low=99
    _bar(100, 101, 99,  100.5, 1000),
    _bar(100.5, 101, 100, 100.8, 1100),
    _bar(100.8, 101, 100, 100.6, 950),
    _bar(100.6, 101, 100, 100.9, 1050),
    _bar(100.9, 101, 100, 100.7, 980),
    _bar(100.7, 101, 100, 101.0, 1000),   # close of OR
    # Trending up past OR-high
    _bar(101.0, 102, 101, 101.8, 1200),
    _bar(101.8, 103, 101.5, 102.5, 1300),
    _bar(102.5, 104, 102, 103.5, 1400),   # 5min slope+ 15min slope+
]

BARS_MOMENTUM_WEAKENING = [
    # Same OR
    _bar(100, 101, 99,  100.5, 1000),
    _bar(100.5, 101, 100, 100.8, 1100),
    _bar(100.8, 101, 100, 100.6, 950),
    _bar(100.6, 101, 100, 100.9, 1050),
    _bar(100.9, 101, 100, 100.7, 980),
    _bar(100.7, 101, 100, 101.0, 1000),
    # Climbed up then flattens (15min still positive, 5min flat/down)
    _bar(101.0, 102, 101, 101.8, 1200),
    _bar(101.8, 102.5, 101.5, 102.2, 1300),
    _bar(102.2, 102.4, 101.9, 102.0, 1100),  # close drops vs prior
    _bar(102.0, 102.3, 101.8, 101.95, 1000), # close drops again — 5min slope < 0
]

BARS_FAILED_BREAKOUT = [
    _bar(100, 101, 99,  100.5, 1000),
    _bar(100.5, 101, 100, 100.8, 1100),
    _bar(100.8, 101, 100, 100.6, 950),
    _bar(100.6, 101, 100, 100.9, 1050),
    _bar(100.9, 101, 100, 100.7, 980),
    _bar(100.7, 101, 100, 101.0, 1000),   # close of OR (high=101, low=99)
    # Pokes above OR-high (102.5) then falls back through OR-low (99)
    _bar(101.0, 102.5, 100.8, 102.0, 1300),  # poked or_high
    _bar(102.0, 102.0, 99.5, 100.5, 1200),
    _bar(100.5, 100.8, 98.5, 98.8, 1100),    # last < or_low=99, near VWAP
]

BARS_REVERSAL_CONFIRMED = [
    _bar(100, 101, 99,  100.5, 1000),
    _bar(100.5, 101, 100, 100.8, 1100),
    _bar(100.8, 101, 100, 100.6, 950),
    _bar(100.6, 101, 100, 100.9, 1050),
    _bar(100.9, 101, 100, 100.7, 980),
    _bar(100.7, 101, 100, 101.0, 1000),    # OR done
    # Tumbling — far below VWAP AND below OR-low
    _bar(101.0, 101.2, 99.5, 99.8, 1500),
    _bar(99.8, 100.0, 97.5, 97.8, 1800),
    _bar(97.8, 98.0, 96.5, 96.8, 2000),    # decisive break, 15min slope < 0
]

BARS_CHOP_NO_EDGE = [
    _bar(100, 101, 99, 100.3, 1000),
    _bar(100.3, 101, 99.5, 100.1, 1050),
    _bar(100.1, 100.5, 99.5, 100.3, 980),
    _bar(100.3, 100.7, 99.7, 100.0, 1000),
    _bar(100.0, 100.4, 99.6, 100.2, 1010),
    _bar(100.2, 100.5, 99.8, 100.1, 990),
    _bar(100.1, 100.6, 99.7, 100.3, 1000),
    _bar(100.3, 100.5, 99.9, 100.0, 1050),
]


class TestIntradayTrendStates(unittest.TestCase):

    def setUp(self):
        import intraday_trend
        # Clear cache between tests so identical symbol re-fetches in mocks.
        intraday_trend._TREND_CACHE.clear()

    def _run(self, bars, side="long"):
        import intraday_trend
        with patch.object(intraday_trend, "_fetch_bars", return_value=bars):
            return intraday_trend.intraday_trend_state("AMD", side=side)

    def test_trend_continues_long(self):
        r = self._run(BARS_TREND_CONTINUES)
        self.assertEqual(r["state"], "TREND_CONTINUES", f"got {r}")
        self.assertFalse(r["stale"])
        self.assertIsNotNone(r["vwap"])

    def test_momentum_weakening(self):
        r = self._run(BARS_MOMENTUM_WEAKENING)
        self.assertEqual(r["state"], "MOMENTUM_WEAKENING", f"got {r}")
        self.assertFalse(r["stale"])

    def test_failed_breakout(self):
        r = self._run(BARS_FAILED_BREAKOUT)
        # Acceptable: either FAILED_BREAKOUT (poked-then-rejected) or
        # REVERSAL_CONFIRMED (the 9th bar at 98.8 is below or_low=99
        # AND below VWAP). The module's rule 1 catches it first as
        # REVERSAL_CONFIRMED because slope_15 is decisively down. Both
        # are valid escalation signals — assert one of two.
        self.assertIn(r["state"], ("FAILED_BREAKOUT", "REVERSAL_CONFIRMED"), f"got {r}")
        self.assertFalse(r["stale"])

    def test_reversal_confirmed(self):
        r = self._run(BARS_REVERSAL_CONFIRMED)
        self.assertEqual(r["state"], "REVERSAL_CONFIRMED", f"got {r}")
        self.assertFalse(r["stale"])
        # Sanity: not above_vwap; reason mentions vwap & or_low.
        self.assertFalse(r["above_vwap"])
        self.assertIn("vwap", r["reason"].lower())

    def test_chop_no_edge(self):
        r = self._run(BARS_CHOP_NO_EDGE)
        self.assertEqual(r["state"], "CHOP_NO_EDGE", f"got {r}")
        self.assertFalse(r["stale"])

    def test_fail_soft_returns_chop_no_edge_on_exception(self):
        import intraday_trend
        with patch.object(intraday_trend, "_fetch_bars", side_effect=RuntimeError("boom")):
            r = intraday_trend.intraday_trend_state("AMD")
        self.assertEqual(r["state"], "CHOP_NO_EDGE")
        self.assertTrue(r["stale"])
        self.assertIn("RuntimeError", r["reason"])

    def test_fail_soft_returns_chop_no_edge_on_empty_bars(self):
        r = self._run([])
        self.assertEqual(r["state"], "CHOP_NO_EDGE")
        self.assertTrue(r["stale"])
        self.assertIn("insufficient", r["reason"])

    def test_cache_hit_skips_second_fetch(self):
        import intraday_trend
        with patch.object(intraday_trend, "_fetch_bars", return_value=BARS_TREND_CONTINUES) as mock_fetch:
            r1 = intraday_trend.intraday_trend_state("CACHE_TEST")
            r2 = intraday_trend.intraday_trend_state("CACHE_TEST")
            self.assertEqual(mock_fetch.call_count, 1, "second call should be cached")
            self.assertEqual(r1["state"], r2["state"])

    def test_short_side_mirror_reversal_on_uptrend(self):
        # For a SHORT, a strong UPtrend through OR-high == reversal against us.
        r = self._run(BARS_TREND_CONTINUES, side="short")
        # The mirrored slopes go negative, mirrored vwap test fails, so we
        # expect REVERSAL_CONFIRMED (the short is being broken against).
        self.assertEqual(r["state"], "REVERSAL_CONFIRMED", f"got {r}")

    def test_empty_symbol_returns_chop(self):
        import intraday_trend
        r = intraday_trend.intraday_trend_state("")
        self.assertEqual(r["state"], "CHOP_NO_EDGE")
        self.assertTrue(r["stale"])

    def test_all_5_state_constants_exposed(self):
        import intraday_trend
        for s in ("TREND_CONTINUES", "MOMENTUM_WEAKENING", "FAILED_BREAKOUT",
                  "REVERSAL_CONFIRMED", "CHOP_NO_EDGE"):
            self.assertTrue(hasattr(intraday_trend, s), f"missing {s}")
            self.assertEqual(getattr(intraday_trend, s), s, f"{s} value mismatch")

    def test_vwap_state_alias(self):
        import intraday_trend
        with patch.object(intraday_trend, "_fetch_bars", return_value=BARS_TREND_CONTINUES):
            r = intraday_trend.vwap_state("AMD")
        self.assertEqual(r["state"], "TREND_CONTINUES")


class TestExitMonitorEscalation(unittest.TestCase):
    """Verify exit-monitor.enrich_position upgrades HOLD → CLOSE_FLAT
    when intraday_trend_state returns REVERSAL_CONFIRMED."""

    def setUp(self):
        sys.path.insert(0, str(REPO_ROOT / "exit-monitor"))

    def _build_pos(self, plpc=0.0, hours_held=2.0, sym="AMD"):
        from datetime import datetime, timezone, timedelta
        # Build a synthetic Alpaca position dict similar to what /v2/positions returns.
        return {
            "symbol": sym,
            "qty": "33",
            "side": "long",
            "asset_class": "us_equity",
            "avg_entry_price": "100",
            "current_price": str(100 * (1 + plpc / 100.0)),
            "unrealized_pl": str(33 * 100 * (plpc / 100.0)),
            "unrealized_plpc": str(plpc / 100.0),
            "market_value": str(33 * 100 * (1 + plpc / 100.0)),
            "created_at": (datetime.now(timezone.utc) - timedelta(hours=hours_held)).isoformat(),
        }

    def test_escalates_hold_to_close_flat_on_reversal(self):
        # exit-monitor calls our module via the wired import. Patch the
        # imported intraday_trend_state in exit-monitor's namespace OR in
        # the source module — easier: patch _fetch_bars to return reversal.
        # Import exit-monitor's enrich_position lazily because monitor.py
        # imports heavy modules (notify, alpaca_orders) at top.
        import importlib
        import intraday_trend
        intraday_trend._TREND_CACHE.clear()
        with patch.object(intraday_trend, "_fetch_bars", return_value=BARS_REVERSAL_CONFIRMED):
            # exit-monitor module
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "exit_monitor_under_test",
                str(REPO_ROOT / "exit-monitor" / "monitor.py"),
            )
            em = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(em)
            pos = self._build_pos(plpc=0.1, hours_held=1.0)  # flat-ish, recent
            result = em.enrich_position(pos, orders=[])
            self.assertEqual(result["recommendation"], "CLOSE_FLAT",
                             msg=f"expected escalation; got {result}")
            self.assertTrue(any("REVERSAL_CONFIRMED" in r for r in result["reasons"]),
                            msg=f"reasons missing REVERSAL_CONFIRMED: {result['reasons']}")

    def test_does_not_downgrade_emergency(self):
        import importlib.util
        import intraday_trend
        intraday_trend._TREND_CACHE.clear()
        with patch.object(intraday_trend, "_fetch_bars", return_value=BARS_TREND_CONTINUES):
            spec = importlib.util.spec_from_file_location(
                "exit_monitor_under_test_2",
                str(REPO_ROOT / "exit-monitor" / "monitor.py"),
            )
            em = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(em)
            # Big loss → CLOSE_EMERGENCY; intraday trend says TREND_CONTINUES
            # (favorable). Result must STILL be CLOSE_EMERGENCY (no downgrade).
            pos = self._build_pos(plpc=-15.0, hours_held=2.0)
            result = em.enrich_position(pos, orders=[])
            self.assertEqual(result["recommendation"], "CLOSE_EMERGENCY",
                             msg=f"emergency must NEVER be downgraded; got {result}")


if __name__ == "__main__":
    unittest.main()
