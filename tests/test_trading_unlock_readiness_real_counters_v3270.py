"""v3.27.0 (2026-06-09) — readiness gate consumes real_market_opportunities_count.

Pin that scaffold records can NEVER advance the broker-paper canary
gate, and that the readiness module reads the v3.26.1
``real_market_opportunities_count`` field directly.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestRealMarketCounterIsTheGate(unittest.TestCase):
    def test_legacy_normal_counter_at_100_does_not_unblock(self):
        # 100 in the LEGACY counter but 0 in the real counter must NOT
        # unblock broker-paper canary.
        from trading_unlock_readiness import (
            UnlockReadinessInputs, evaluate_unlock_readiness,
            SIGNAL_SHADOW_UNLOCK_READY,
        )
        i = UnlockReadinessInputs(
            real_market_opportunities_count=0,
            normal_non_halt_opportunities_count=100,
            completed_shadow_outcomes_count=25,
            daily_learning_stable=True,
            trade_reconstruction_stable=True,
            explicit_operator_approval_for_broker_paper=True,
        )
        r = evaluate_unlock_readiness(i)
        self.assertEqual(r.verdict, SIGNAL_SHADOW_UNLOCK_READY)
        missing = " ".join(r.missing_for_broker_paper)
        self.assertIn("real_market_opportunities_count", missing)

    def test_real_counter_at_50_clears_threshold(self):
        from trading_unlock_readiness import (
            UnlockReadinessInputs, evaluate_unlock_readiness,
            BROKER_PAPER_CANARY_READY,
        )
        i = UnlockReadinessInputs(
            real_market_opportunities_count=50,
            normal_non_halt_opportunities_count=0,  # legacy stays 0
            completed_shadow_outcomes_count=25,
            daily_learning_stable=True,
            trade_reconstruction_stable=True,
            explicit_operator_approval_for_broker_paper=True,
        )
        r = evaluate_unlock_readiness(i)
        self.assertEqual(r.verdict, BROKER_PAPER_CANARY_READY)


class TestScaffoldDoesNotCount(unittest.TestCase):
    def test_scaffold_counter_field_is_observational(self):
        # The unlock readiness inputs MUST NOT have a
        # scaffold_no_market_data_records_count field — scaffold
        # records are intentionally invisible to the gate.
        from trading_unlock_readiness import UnlockReadinessInputs
        i = UnlockReadinessInputs()
        self.assertFalse(
            hasattr(i, "scaffold_no_market_data_records_count"),
            "scaffold counter must NOT be a readiness input",
        )


class TestEvaluateFromCurrentRepoStateLoadsCounters(unittest.TestCase):
    def test_loads_real_market_counter_from_disk(self):
        from trading_unlock_readiness import (
            evaluate_from_current_repo_state,
            SIGNAL_SHADOW_UNLOCK_READY,
        )
        r = evaluate_from_current_repo_state()
        # Current real_market_opportunities_count is 0 — broker
        # paper must be blocked AND the missing list must reference
        # real_market_opportunities_count.
        self.assertEqual(r.verdict, SIGNAL_SHADOW_UNLOCK_READY)
        missing = " ".join(r.missing_for_broker_paper)
        self.assertIn("real_market_opportunities_count", missing)
        self.assertIn("< 50", missing)


class TestLiveTradingAlwaysBlocked(unittest.TestCase):
    def test_live_never_returns_ready(self):
        from trading_unlock_readiness import (
            UnlockReadinessInputs, evaluate_unlock_readiness,
            BROKER_PAPER_CANARY_READY, LIVE_TRADING_NOT_SUPPORTED,
        )
        i = UnlockReadinessInputs(
            real_market_opportunities_count=999,
            completed_shadow_outcomes_count=999,
            daily_learning_stable=True,
            trade_reconstruction_stable=True,
            explicit_operator_approval_for_broker_paper=True,
        )
        r = evaluate_unlock_readiness(i)
        # The highest possible verdict is broker-paper canary ready;
        # live trading is never returned as a positive verdict.
        self.assertNotEqual(r.verdict, LIVE_TRADING_NOT_SUPPORTED)
        self.assertEqual(r.verdict, BROKER_PAPER_CANARY_READY)
        # higher_tier_status is the informational marker.
        self.assertEqual(
            r.details["higher_tier_status"],
            LIVE_TRADING_NOT_SUPPORTED,
        )


if __name__ == "__main__":
    unittest.main()
