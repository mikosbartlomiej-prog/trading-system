"""v3.25 — Tests for the conditional outcome scheduling script."""
from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
if str(REPO_ROOT / "shared") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "shared"))

import run_conditional_outcome_scheduling as mod


def _fill_record() -> dict:
    return {
        "fill_status":   "FILLED",
        "timestamp_iso": "2026-06-15T12:00:00Z",
        "fill_price":    100.0,
        "qty":           1.0,
        "side":          "long",
        "symbol":        "AAPL",
        "strategy":      "momentum-long",
        "asset_class":   "us_equity",
        "signal_id":     "abc",
    }


class TestNoOutcomesWhenNoFills(unittest.TestCase):
    def test_empty_ledger_results_in_no_outcomes(self) -> None:
        result = mod.schedule_for_fills([])
        self.assertEqual(result, [])

    def test_main_with_no_fills_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            mod.SHADOW_LEDGER_DIR = td_path / "shadow_ledger"
            mod.SHADOW_OUTCOMES_DIR = td_path / "shadow_outcomes"
            rc = mod.main(["--date", "2026-06-15"])
            self.assertEqual(rc, 0)
            outpath = mod.SHADOW_OUTCOMES_DIR / "2026-06-15.jsonl"
            self.assertFalse(outpath.exists())


class TestOutcomesScheduledWhenFillsExist(unittest.TestCase):
    def test_one_fill_produces_at_least_one_outcome(self) -> None:
        outcomes = mod.schedule_for_fills([_fill_record()])
        # outcome_tracker.OUTCOME_HORIZONS has multiple horizons,
        # so a single fill yields multiple ScheduledOutcomes.
        self.assertGreaterEqual(len(outcomes), 1)
        for o in outcomes:
            self.assertEqual(o.get("record_type"),
                              "SHADOW_OUTCOME_PENDING")


class TestOutcomesMarkedIsPaperTradeFalse(unittest.TestCase):
    def test_every_scheduled_outcome_is_paper_trade_false(self) -> None:
        outcomes = mod.schedule_for_fills([_fill_record()])
        self.assertTrue(outcomes, "must have ≥1 outcome for this assertion")
        for o in outcomes:
            self.assertIn("is_paper_trade", o)
            self.assertFalse(o["is_paper_trade"])
            # Standing markers re-asserted on every record.
            self.assertIn("standing_markers", o)
            for m in mod.STANDING_MARKERS:
                self.assertIn(m, o["standing_markers"])


class TestNoBrokerCall(unittest.TestCase):
    def test_script_does_not_import_alpaca_orders(self) -> None:
        src = Path(mod.__file__).read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("alpaca_orders", alias.name)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn("alpaca_orders", node.module or "")

    def test_script_does_not_reference_broker_entry_points(self) -> None:
        src = Path(mod.__file__).read_text()
        for name in (
            "submit_order(", "place_order(", "safe_close(",
            "place_stock_order(", "place_crypto_order(",
            "place_option_order(", "close_position(",
            "close_all_positions(",
        ):
            self.assertNotIn(name, src)

    def test_script_does_not_import_network_libs(self) -> None:
        src = Path(mod.__file__).read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name, (
                        "requests", "urllib.request",
                        "httpx", "http.client",
                    ))


if __name__ == "__main__":
    unittest.main()
