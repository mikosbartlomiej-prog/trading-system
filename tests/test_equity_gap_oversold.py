"""
Tests for learning-loop/analyzer.py v3.8.9 alerts:
  - compute_equity_gap_alert  (LLM proposal 2026-05-18)
  - compute_oversold_alerts   (LLM proposal 2026-05-18)

Both surface to today_stats payload + rationale.md so Senior PM sees
unexplained equity moves and RSI extremes without manual investigation.
"""

import importlib.util
import os
import sys
import unittest


# Same import-trick as test_analyzer_strategy_parse.py — exec the
# analyzer.py prefix that defines our helpers, avoiding heavy imports
# that need newer Python.
_ANALYZER_PATH = os.path.join(os.path.dirname(__file__), "..", "learning-loop", "analyzer.py")
_NAMESPACE: dict = {}
with open(_ANALYZER_PATH, encoding="utf-8") as f:
    _src = f.read()
# We only need the equity-gap + oversold helpers (added between the
# RSI snapshot section and compute_position_audit).
_start = _src.find("def compute_equity_gap_alert")
_end   = _src.find("# ─── Position audit")
assert _start > 0 and _end > _start, "equity-gap helpers anchors not found"
_snippet = _src[_start:_end]
exec(_snippet, _NAMESPACE)
compute_equity_gap_alert = _NAMESPACE["compute_equity_gap_alert"]
compute_oversold_alerts  = _NAMESPACE["compute_oversold_alerts"]


class TestEquityGap(unittest.TestCase):

    def test_no_gap_when_change_small(self):
        stats = {"equity": 95400, "cumulative_trades": 0}
        result = compute_equity_gap_alert(stats, prev_equity=95000)
        self.assertIsNone(result)   # $400 delta < $500 threshold

    def test_no_gap_when_trades_attributed(self):
        stats = {"equity": 94000, "cumulative_trades": 3}
        result = compute_equity_gap_alert(stats, prev_equity=95000)
        self.assertIsNone(result)   # delta explained by 3 closed trades

    def test_warn_severity_when_drop_above_1k(self):
        stats = {"equity": 93500, "cumulative_trades": 0}
        result = compute_equity_gap_alert(stats, prev_equity=95000)
        self.assertIsNotNone(result)
        self.assertEqual(result["severity"], "WARN")
        self.assertEqual(result["delta_usd"], -1500.0)
        self.assertIn("dropped", result["message"])

    def test_info_severity_when_500_to_1k(self):
        stats = {"equity": 95800, "cumulative_trades": 0}
        result = compute_equity_gap_alert(stats, prev_equity=95000)
        self.assertIsNotNone(result)
        self.assertEqual(result["severity"], "INFO")
        self.assertEqual(result["delta_usd"], 800.0)
        self.assertIn("increased", result["message"])

    def test_returns_none_on_missing_data(self):
        self.assertIsNone(compute_equity_gap_alert({"equity": 0}, 95000))
        self.assertIsNone(compute_equity_gap_alert({"equity": 95000}, 0))
        self.assertIsNone(compute_equity_gap_alert({}, 95000))


class TestOversoldAlerts(unittest.TestCase):

    def test_no_alerts_on_empty_snapshot(self):
        self.assertEqual(compute_oversold_alerts({}), [])

    def test_oversold_eth_alert(self):
        snap = {"ETH/USD": {"today": 25.7, "regime": "oversold"}}
        result = compute_oversold_alerts(snap)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "ETH/USD")
        self.assertEqual(result[0]["kind"], "pre-signal")
        self.assertEqual(result[0]["regime"], "oversold")
        self.assertIn("25.7", result[0]["message"])

    def test_overbought_spy_alert(self):
        snap = {"SPY": {"today": 82.5, "regime": "overbought"}}
        result = compute_oversold_alerts(snap)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["kind"], "fade-risk")
        self.assertEqual(result[0]["regime"], "overbought")

    def test_neutral_no_alert(self):
        snap = {"BTC/USD": {"today": 55.0, "regime": "neutral"}}
        self.assertEqual(compute_oversold_alerts(snap), [])

    def test_threshold_boundary(self):
        # Exactly at threshold → should fire (use <=)
        snap = {"ETH/USD": {"today": 30.0}}
        result = compute_oversold_alerts(snap, threshold=30.0)
        self.assertEqual(len(result), 1)
        # Just above
        snap = {"ETH/USD": {"today": 30.1}}
        self.assertEqual(compute_oversold_alerts(snap, threshold=30.0), [])

    def test_multi_symbol(self):
        snap = {
            "SPY":     {"today": 82.5},   # overbought
            "BTC/USD": {"today": 55.0},   # neutral, no alert
            "ETH/USD": {"today": 25.7},   # oversold
        }
        result = compute_oversold_alerts(snap)
        kinds = sorted([(a["symbol"], a["kind"]) for a in result])
        self.assertEqual(kinds, [("ETH/USD", "pre-signal"), ("SPY", "fade-risk")])


if __name__ == "__main__":
    unittest.main()
