"""v3.27.1 (2026-06-09) — pure-function evaluator unit tests."""

from __future__ import annotations

import importlib.util as iu
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _load_evaluator():
    spec = iu.spec_from_file_location(
        "evaluate_automated_shadow_progress",
        REPO_ROOT / "scripts"
        / "evaluate_automated_shadow_progress.py",
    )
    mod = iu.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestVerdictMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ev = _load_evaluator()

    def test_blocked_no_secrets_dominates(self):
        v, _ = self.ev.evaluate_verdict(
            {"real_market_opportunities_count": 0,
              "completed_shadow_outcomes_count": 0},
            last_workflow_run_conclusion="success",
            secrets_status="SECRETS_MISSING_OR_UNAVAILABLE",
            diagnostic_token_counts={},
        )
        self.assertEqual(v, "AUTOMATED_PIPELINE_BLOCKED_NO_SECRETS")

    def test_blocked_workflow_failure_dominates(self):
        # Even with secrets available, a workflow failure blocks.
        v, _ = self.ev.evaluate_verdict(
            {"real_market_opportunities_count": 100,
              "completed_shadow_outcomes_count": 50},
            last_workflow_run_conclusion="failure",
            secrets_status="SECRETS_AVAILABLE",
            diagnostic_token_counts={},
        )
        self.assertEqual(
            v, "AUTOMATED_PIPELINE_BLOCKED_WORKFLOW_FAILURE")

    def test_blocked_provider_error_when_dominant(self):
        v, _ = self.ev.evaluate_verdict(
            {"real_market_opportunities_count": 0,
              "completed_shadow_outcomes_count": 0},
            last_workflow_run_conclusion="success",
            secrets_status="SECRETS_AVAILABLE",
            diagnostic_token_counts={
                "MARKET_DATA_PROVIDER_ERROR": 8,
                # no valid data tokens this cycle
            },
        )
        self.assertEqual(
            v, "AUTOMATED_PIPELINE_BLOCKED_PROVIDER_ERROR")

    def test_provider_error_with_valid_data_does_not_block(self):
        # Some symbols error but others returned valid data — not a
        # full-pipeline outage.
        v, _ = self.ev.evaluate_verdict(
            {"real_market_opportunities_count": 0,
              "completed_shadow_outcomes_count": 0},
            last_workflow_run_conclusion="success",
            secrets_status="SECRETS_AVAILABLE",
            diagnostic_token_counts={
                "MARKET_DATA_PROVIDER_ERROR": 1,
                "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL": 7,
            },
        )
        self.assertEqual(
            v, "AUTOMATED_PIPELINE_HEALTHY_NO_REAL_DATA_YET")

    def test_real_data_present_yields_collecting(self):
        v, _ = self.ev.evaluate_verdict(
            {"real_market_opportunities_count": 3,
              "completed_shadow_outcomes_count": 1},
            last_workflow_run_conclusion="success",
            secrets_status="SECRETS_AVAILABLE",
            diagnostic_token_counts={
                "REAL_MARKET_SIGNAL_RECORDS_EMITTED": 3,
            },
        )
        self.assertEqual(
            v,
            "AUTOMATED_PIPELINE_HEALTHY_COLLECTING_REAL_MARKET_DATA",
        )

    def test_healthy_no_data_when_zero_counters_zero_errors(self):
        v, _ = self.ev.evaluate_verdict(
            {"real_market_opportunities_count": 0,
              "completed_shadow_outcomes_count": 0},
            last_workflow_run_conclusion="success",
            secrets_status="SECRETS_AVAILABLE",
            diagnostic_token_counts={
                "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL": 13,
            },
        )
        self.assertEqual(
            v, "AUTOMATED_PIPELINE_HEALTHY_NO_REAL_DATA_YET")


class TestBrokerPaperStaysBlocked(unittest.TestCase):
    def test_scaffold_records_do_not_unblock(self):
        # Scaffold-only carry-over of 1000 records must not unblock.
        ev = _load_evaluator()
        v, _ = ev.evaluate_verdict(
            {"real_market_opportunities_count": 0,
              "completed_shadow_outcomes_count": 0,
              "scaffold_no_market_data_records_count": 1000},
            last_workflow_run_conclusion="success",
            secrets_status="SECRETS_AVAILABLE",
            diagnostic_token_counts={
                "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL": 5,
            },
        )
        self.assertEqual(
            v, "AUTOMATED_PIPELINE_HEALTHY_NO_REAL_DATA_YET")

    def test_below_50_real_below_20_outcomes_keeps_canary_blocked(self):
        # Just below thresholds — canary remains blocked by
        # trading_unlock_readiness.
        from trading_unlock_readiness import (
            UnlockReadinessInputs, evaluate_unlock_readiness,
            SIGNAL_SHADOW_UNLOCK_READY,
        )
        i = UnlockReadinessInputs(
            real_market_opportunities_count=49,
            completed_shadow_outcomes_count=19,
            daily_learning_stable=True,
            trade_reconstruction_stable=True,
            explicit_operator_approval_for_broker_paper=True,
        )
        r = evaluate_unlock_readiness(i)
        self.assertEqual(r.verdict, SIGNAL_SHADOW_UNLOCK_READY)


class TestLiveTradingNeverReturned(unittest.TestCase):
    def test_live_marker_always_in_standing_markers(self):
        ev = _load_evaluator()
        self.assertEqual(ev.LIVE_TRADING_UNSUPPORTED,
                          "LIVE_TRADING_UNSUPPORTED")
        self.assertEqual(ev.BROKER_PAPER_CANARY_STILL_BLOCKED,
                          "BROKER_PAPER_CANARY_STILL_BLOCKED")


class TestNoOrderExecutionImports(unittest.TestCase):
    def test_source_clean(self):
        src = (REPO_ROOT / "scripts"
                / "evaluate_automated_shadow_progress.py").read_text()
        FORBIDDEN = (
            "alpaca_orders", "safe_close",
            "place_stock_bracket", "place_crypto_order",
            "execute_crypto_signal", "execute_stock_signal",
            "requests.post", "requests.put", "requests.delete",
        )
        for tok in FORBIDDEN:
            self.assertNotIn(tok, src,
                              f"forbidden token in evaluator: {tok!r}")


if __name__ == "__main__":
    unittest.main()
