"""v3.11 Phase B — auto-prune SILENT zombie strategies after 21 days."""

import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import _path  # noqa: F401

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "learning-loop")))

import unittest
from datetime import datetime, timezone, timedelta

from adapter import _flag_silent_strategies


def _state_with_strategy(name, enabled=True, hard_safety_override=False,
                          days_ago_enabled=30, days_tracked=30):
    enabled_at = (datetime.now(timezone.utc).date() - timedelta(days=days_ago_enabled)).isoformat()
    return {
        "days_tracked": days_tracked,
        "strategies": {
            name: {
                "enabled": enabled,
                "hard_safety_override": hard_safety_override,
                "enabled_at": enabled_at,
            }
        }
    }


def _stats_no_trades(name, placed_lifetime=10):
    """v3.11.1: by default include placed_lifetime≥5 so legit auto-prune
    path fires. Tests that want PIPELINE_FAILURE branch override to 0."""
    return {
        "by_strategy": {name: {"trades_lifetime": 0, "trades_7d": 0}},
        "fill_rate": {name: {"placed_lifetime": placed_lifetime, "placed": placed_lifetime}},
    }


class TestZombiePrune(unittest.TestCase):

    def test_silent_under_threshold_warns_only(self):
        state = _state_with_strategy("test-strat", days_ago_enabled=15, days_tracked=15)
        stats = _stats_no_trades("test-strat")
        out = _flag_silent_strategies(state, stats, min_days=10)
        # < 21 days → warning only, NOT pruned
        self.assertTrue(state["strategies"]["test-strat"]["enabled"])
        # v3.11.1: message changed from "will auto-prune" to "will evaluate at 21d"
        self.assertTrue(any("SILENT" in m and ("will evaluate at" in m or "will auto-prune" in m) for m in out))

    def test_silent_at_or_above_threshold_auto_prunes(self):
        state = _state_with_strategy("zombie-strat", days_ago_enabled=25, days_tracked=25)
        stats = _stats_no_trades("zombie-strat")
        out = _flag_silent_strategies(state, stats, min_days=10)
        # ≥ 21 days → auto-prune
        self.assertFalse(state["strategies"]["zombie-strat"]["enabled"])
        self.assertTrue(state["strategies"]["zombie-strat"].get("hard_safety"))
        self.assertIsNotNone(state["strategies"]["zombie-strat"].get("auto_pruned_at"))
        self.assertTrue(any("AUTO-PRUNED" in m for m in out))

    def test_override_keeps_enabled_despite_silence(self):
        state = _state_with_strategy("kept-alive", days_ago_enabled=50,
                                       hard_safety_override=True)
        stats = _stats_no_trades("kept-alive")
        out = _flag_silent_strategies(state, stats, min_days=10)
        # Override → stays enabled
        self.assertTrue(state["strategies"]["kept-alive"]["enabled"])
        self.assertTrue(any("hard_safety_override=true" in m for m in out))

    def test_strategy_with_trades_not_pruned(self):
        state = _state_with_strategy("active-strat", days_ago_enabled=50, days_tracked=50)
        # Has trades → not SILENT
        stats = {
            "by_strategy": {"active-strat": {"trades_lifetime": 5, "trades_7d": 2}},
            "days_tracked": 50,
        }
        out = _flag_silent_strategies(state, stats, min_days=10)
        # No warning, no prune
        self.assertTrue(state["strategies"]["active-strat"]["enabled"])
        prune_msgs = [m for m in out if "AUTO-PRUNED" in m or "active-strat" in m]
        self.assertEqual(len(prune_msgs), 0)


    # v3.11.1 — new tests for refined policy

    def test_v311_1_pipeline_failure_not_pruned(self):
        """v3.11.1: 21+d SILENT but 0 placement attempts → PIPELINE_FAILURE,
        NOT auto-pruned. Real production case (crypto-momentum 2026-05-28)."""
        state = _state_with_strategy("crypto-pipeline-broken",
                                       days_ago_enabled=44, days_tracked=44)
        stats = _stats_no_trades("crypto-pipeline-broken", placed_lifetime=0)
        out = _flag_silent_strategies(state, stats, min_days=10)
        # KEY ASSERTION: NOT pruned (enabled stays True)
        self.assertTrue(state["strategies"]["crypto-pipeline-broken"]["enabled"],
            "v3.11.1: pipeline failure (0 placements) must NOT auto-prune")
        self.assertTrue(any("PIPELINE_FAILURE_SUSPECTED" in m for m in out))

    def test_v311_1_legit_no_edge_pruned(self):
        """v3.11.1: 21+d SILENT WITH placement attempts → legit prune."""
        state = _state_with_strategy("legit-zombie",
                                       days_ago_enabled=30, days_tracked=30)
        stats = _stats_no_trades("legit-zombie", placed_lifetime=8)
        out = _flag_silent_strategies(state, stats, min_days=10)
        # Pruned
        self.assertFalse(state["strategies"]["legit-zombie"]["enabled"])
        self.assertTrue(any("AUTO-PRUNED" in m for m in out))

    def test_v311_1_low_sample_not_pruned(self):
        """v3.11.1: between 1-4 placements → insufficient sample, NOT pruned."""
        state = _state_with_strategy("low-sample",
                                       days_ago_enabled=25, days_tracked=25)
        stats = _stats_no_trades("low-sample", placed_lifetime=2)
        out = _flag_silent_strategies(state, stats, min_days=10)
        # NOT pruned (sample too low)
        self.assertTrue(state["strategies"]["low-sample"]["enabled"])
        self.assertTrue(any("insufficient sample" in m for m in out))


if __name__ == "__main__":
    unittest.main()
