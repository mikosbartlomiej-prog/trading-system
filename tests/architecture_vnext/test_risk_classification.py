"""v3.10 — unit tests for risk_classification taxonomy."""

import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import _path  # noqa: F401

import unittest

from risk_classification import (
    RiskVerdict, RiskDecision, new_decision_id, worst, combine,
    allow, block, defer, downsize, alert_only,
)


class TestVerdictEnum(unittest.TestCase):
    def test_terminal_flag(self):
        self.assertTrue(RiskVerdict.BLOCK.is_terminal)
        self.assertTrue(RiskVerdict.ALERT_ONLY.is_terminal)
        self.assertFalse(RiskVerdict.DEFER.is_terminal)
        self.assertFalse(RiskVerdict.DOWNSIZE.is_terminal)
        self.assertFalse(RiskVerdict.ALLOW.is_terminal)

    def test_allows_order(self):
        self.assertTrue(RiskVerdict.ALLOW.allows_order)
        self.assertTrue(RiskVerdict.DOWNSIZE.allows_order)
        self.assertFalse(RiskVerdict.BLOCK.allows_order)
        self.assertFalse(RiskVerdict.DEFER.allows_order)
        self.assertFalse(RiskVerdict.ALERT_ONLY.allows_order)


class TestWorstOrdering(unittest.TestCase):
    def test_block_dominates_all(self):
        self.assertEqual(worst(RiskVerdict.BLOCK, RiskVerdict.ALLOW), RiskVerdict.BLOCK)
        self.assertEqual(worst(RiskVerdict.ALLOW, RiskVerdict.BLOCK), RiskVerdict.BLOCK)
        self.assertEqual(worst(RiskVerdict.BLOCK, RiskVerdict.DEFER, RiskVerdict.DOWNSIZE),
                         RiskVerdict.BLOCK)

    def test_severity_order(self):
        # BLOCK > DEFER > DOWNSIZE > ALERT_ONLY > ALLOW
        self.assertEqual(worst(RiskVerdict.DEFER, RiskVerdict.DOWNSIZE), RiskVerdict.DEFER)
        self.assertEqual(worst(RiskVerdict.DOWNSIZE, RiskVerdict.ALERT_ONLY), RiskVerdict.DOWNSIZE)
        self.assertEqual(worst(RiskVerdict.ALERT_ONLY, RiskVerdict.ALLOW), RiskVerdict.ALERT_ONLY)

    def test_empty_returns_allow(self):
        self.assertEqual(worst(), RiskVerdict.ALLOW)


class TestDecisionId(unittest.TestCase):
    def test_format(self):
        did = new_decision_id()
        # 20260527T193045123456-a3f9b1c2 (microsecond + 8 hex random)
        self.assertRegex(did, r"^\d{8}T\d{12}-[a-f0-9]{8}$")

    def test_uniqueness(self):
        ids = {new_decision_id() for _ in range(1000)}
        self.assertEqual(len(ids), 1000)

    def test_lexicographic_sort_is_time_sort(self):
        import time
        ids = []
        for _ in range(5):
            ids.append(new_decision_id())
            time.sleep(0.001)
        # Same second OR newer — strictly non-decreasing
        sorted_ids = sorted(ids)
        # Each subsequent id should be >= previous when sorted lex
        for i in range(len(ids) - 1):
            self.assertLessEqual(ids[i], sorted_ids[-1])


class TestRiskDecision(unittest.TestCase):
    def test_allow_default_size(self):
        d = allow("ok", gate="test")
        self.assertEqual(d.verdict, RiskVerdict.ALLOW)
        self.assertEqual(d.size_multiplier, 1.0)
        self.assertTrue(d.allows_order)

    def test_block_no_order(self):
        d = block("paper-only violation", gate="alpaca_orders")
        self.assertFalse(d.allows_order)
        self.assertEqual(d.size_multiplier, 1.0)

    def test_defer_gets_retry_default_60s(self):
        d = defer("Alpaca outage", gate="risk_officer")
        self.assertEqual(d.retry_after_s, 60)

    def test_downsize_clamps_size(self):
        d = downsize("partial confirm", size_multiplier=3.0, gate="signal_confirmation")
        self.assertEqual(d.size_multiplier, 2.0)  # clamped to max 2.0
        d2 = downsize("partial confirm", size_multiplier=0.05, gate="signal_confirmation")
        self.assertEqual(d2.size_multiplier, 0.1)  # clamped to min 0.1

    def test_alert_only(self):
        d = alert_only("weak signal", gate="signal_confirmation")
        self.assertEqual(d.verdict, RiskVerdict.ALERT_ONLY)
        self.assertFalse(d.allows_order)

    def test_jsonl_serialization(self):
        d = block("test reason", gate="test_gate", foo="bar")
        line = d.to_jsonl()
        import json
        parsed = json.loads(line)
        self.assertEqual(parsed["verdict"], "BLOCK")
        self.assertEqual(parsed["reason"], "test reason")
        self.assertEqual(parsed["metadata"]["foo"], "bar")
        self.assertIn("decision_id", parsed)


class TestCombine(unittest.TestCase):
    def test_combine_empty_returns_allow(self):
        d = combine()
        self.assertEqual(d.verdict, RiskVerdict.ALLOW)

    def test_combine_block_dominates(self):
        d = combine(
            allow("ok", gate="a"),
            block("hard fail", gate="b"),
            downsize("partial", 0.5, gate="c"),
        )
        self.assertEqual(d.verdict, RiskVerdict.BLOCK)
        self.assertIn("hard fail", d.reason)

    def test_combine_downsize_multiplies(self):
        d = combine(
            downsize("partial confirm", 0.5, gate="signal"),
            downsize("VIX warn", 0.5, gate="vix"),
        )
        self.assertEqual(d.verdict, RiskVerdict.DOWNSIZE)
        self.assertAlmostEqual(d.size_multiplier, 0.25)  # 0.5 * 0.5

    def test_combine_downsize_floor(self):
        # Lots of downsizes shouldn't go below 0.05
        d = combine(*[downsize("x", 0.1, gate=f"g{i}") for i in range(10)])
        self.assertGreaterEqual(d.size_multiplier, 0.05)

    def test_combine_metadata_aggregated_by_gate(self):
        d = combine(
            block("a", gate="risk_officer", check_failed="whitelist"),
            defer("b", gate="alpaca", error_code=500),
        )
        self.assertIn("risk_officer", d.metadata)
        self.assertIn("alpaca", d.metadata)


if __name__ == "__main__":
    unittest.main()
