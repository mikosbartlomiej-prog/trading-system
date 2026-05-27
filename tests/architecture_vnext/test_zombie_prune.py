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


def _stats_no_trades(name):
    return {
        "by_strategy": {name: {"trades_lifetime": 0, "trades_7d": 0}},
    }


class TestZombiePrune(unittest.TestCase):

    def test_silent_under_threshold_warns_only(self):
        state = _state_with_strategy("test-strat", days_ago_enabled=15, days_tracked=15)
        stats = _stats_no_trades("test-strat")
        out = _flag_silent_strategies(state, stats, min_days=10)
        # < 21 days → warning only, NOT pruned
        self.assertTrue(state["strategies"]["test-strat"]["enabled"])
        self.assertTrue(any("SILENT" in m and "will auto-prune" in m for m in out))

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


if __name__ == "__main__":
    unittest.main()
