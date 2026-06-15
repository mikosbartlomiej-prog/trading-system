"""v3.24 (2026-06-15) — tests for shared/near_miss_tracker.py.

Covers:
  * NearMiss dataclass and record_near_miss persistence
  * is_paper_trade=False + is_signal=False hard-coded invariants
  * evaluate_threshold_realism aggregation + advisory flag logic
  * AST scan ensures module does NOT import alpaca_orders or network libs
  * Module never raises on filesystem error (fail-soft)
  * load_recent_rows returns empty list when dir does not exist

HARD SAFETY
-----------
- No broker, no network, no auto-threshold-adjustment.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_DIR = REPO_ROOT / "shared"
for p in (str(REPO_ROOT), str(SHARED_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import near_miss_tracker as nm  # noqa: E402


class TestNearMissRecord(unittest.TestCase):
    def test_record_returns_dict_with_hard_invariants(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["NEAR_MISS_DIR"] = td
            try:
                d = nm.record_near_miss(
                    "crypto-momentum", "BTC/USD", "rsi",
                    49.8, 50.0)
            finally:
                del os.environ["NEAR_MISS_DIR"]
        self.assertEqual(d["is_paper_trade"], False)
        self.assertEqual(d["is_signal"], False)
        self.assertEqual(d["strategy_id"], "crypto-momentum")
        self.assertEqual(d["symbol"], "BTC/USD")
        self.assertEqual(d["metric_name"], "rsi")
        self.assertAlmostEqual(d["current_value"], 49.8)
        self.assertAlmostEqual(d["threshold"], 50.0)
        self.assertAlmostEqual(d["distance_to_trigger"], -0.2)

    def test_distance_calculated_signed(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["NEAR_MISS_DIR"] = td
            try:
                pos = nm.record_near_miss("s", "X", "vol",
                                            120.0, 100.0)
                neg = nm.record_near_miss("s", "X", "vol",
                                            80.0, 100.0)
            finally:
                del os.environ["NEAR_MISS_DIR"]
        self.assertEqual(pos["distance_to_trigger"], 20.0)
        self.assertEqual(neg["distance_to_trigger"], -20.0)

    def test_invalid_input_does_not_raise(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["NEAR_MISS_DIR"] = td
            try:
                # NaN-style inputs should fail-soft to 0.0 floats.
                d = nm.record_near_miss(
                    "s", "X", "m",
                    float("nan"), float("inf"))
            finally:
                del os.environ["NEAR_MISS_DIR"]
        self.assertEqual(d["current_value"], 0.0)
        # inf is a real float; safe_float keeps it; allow that.
        self.assertIn("distance_to_trigger", d)

    def test_persists_to_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            target = tdp / "today.jsonl"
            d1 = nm.record_near_miss("s", "X", "m", 1.0, 2.0,
                                       path=target)
            d2 = nm.record_near_miss("s", "X", "m", 3.0, 2.0,
                                       path=target)
            self.assertTrue(target.exists())
            lines = target.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            for line in lines:
                row = json.loads(line)
                self.assertFalse(row["is_paper_trade"])
                self.assertFalse(row["is_signal"])


class TestRealismEvaluation(unittest.TestCase):
    def test_empty_rows(self):
        out = nm.evaluate_threshold_realism([])
        self.assertEqual(out["pairs"], [])
        self.assertEqual(out["flagged"], [])

    def test_small_sample_not_flagged(self):
        # min_sample default 10; 3 rows must NOT be flagged.
        rows = [
            {"strategy_id": "s", "metric_name": "rsi",
             "current_value": 49.0, "threshold": 50.0,
             "distance_to_trigger": -1.0},
        ] * 3
        out = nm.evaluate_threshold_realism(rows)
        # 1 pair, advisory_flag False
        self.assertEqual(len(out["pairs"]), 1)
        self.assertFalse(out["pairs"][0]["advisory_flag"])
        self.assertEqual(out["flagged"], [])

    def test_large_sample_close_distance_not_flagged(self):
        # 95th percentile abs distance very small relative to threshold.
        rows = [
            {"strategy_id": "s", "metric_name": "rsi",
             "current_value": 49.9 + (i * 0.001),
             "threshold": 50.0,
             "distance_to_trigger": -0.1 + (i * 0.001)}
            for i in range(15)
        ]
        out = nm.evaluate_threshold_realism(rows)
        self.assertEqual(len(out["pairs"]), 1)
        self.assertFalse(out["pairs"][0]["advisory_flag"])

    def test_large_sample_far_distance_flagged(self):
        # 95th percentile abs distance is huge relative to threshold.
        rows = [
            {"strategy_id": "s", "metric_name": "vol",
             "current_value": 0.0, "threshold": 100.0,
             "distance_to_trigger": -100.0}
            for _ in range(20)
        ]
        out = nm.evaluate_threshold_realism(rows)
        self.assertEqual(len(out["pairs"]), 1)
        p = out["pairs"][0]
        self.assertTrue(p["advisory_flag"])
        self.assertIn("operator review", p["advisory_reason"])
        self.assertEqual(len(out["flagged"]), 1)

    def test_advisory_is_only_advisory(self):
        # The function must NEVER report having mutated a threshold.
        rows = [
            {"strategy_id": "s", "metric_name": "vol",
             "current_value": 0.0, "threshold": 100.0,
             "distance_to_trigger": -100.0}
            for _ in range(20)
        ]
        out = nm.evaluate_threshold_realism(rows)
        for p in out["pairs"]:
            # No mutation field exposed
            self.assertNotIn("new_threshold", p)
            self.assertNotIn("threshold_adjusted", p)


class TestLoader(unittest.TestCase):
    def test_load_recent_rows_no_dir(self):
        rows = nm.load_recent_rows(base_dir="/nonexistent/path/x")
        self.assertEqual(rows, [])

    def test_load_recent_rows_finds_yesterday(self):
        as_of = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "2026-06-14.jsonl").write_text(
                json.dumps({"strategy_id": "s", "metric_name": "rsi",
                              "current_value": 1.0, "threshold": 2.0,
                              "distance_to_trigger": -1.0,
                              "is_paper_trade": False,
                              "is_signal": False,
                              "timestamp_iso": "x"}) + "\n",
                encoding="utf-8")
            rows = nm.load_recent_rows(days=7, base_dir=tdp, as_of=as_of)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["strategy_id"], "s")


class TestSafety(unittest.TestCase):
    def test_module_does_not_import_alpaca_orders(self):
        src = (SHARED_DIR / "near_miss_tracker.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(
                        "alpaca_orders", alias.name or "")
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn(
                    "alpaca_orders", node.module or "")

    def test_module_does_not_make_network_calls(self):
        src = (SHARED_DIR / "near_miss_tracker.py").read_text(
            encoding="utf-8")
        for forbidden in ("import requests", "from requests",
                           "urllib.request", "http.client",
                           "socket.connect"):
            self.assertNotIn(forbidden, src)

    def test_invariant_constants_present(self):
        # The static enforcement module exposes these so other scripts
        # can grep for them.
        self.assertTrue(nm.NEVER_SUBMITS_ORDERS)
        self.assertTrue(nm.NEVER_IMPORTS_ALPACA_ORDERS)
        self.assertTrue(nm.NEVER_COUNTS_AS_TRADE)
        self.assertTrue(nm.NEVER_COUNTS_AS_SIGNAL)
        self.assertTrue(nm.NEVER_AUTO_ADJUSTS_THRESHOLD)


if __name__ == "__main__":
    unittest.main()
