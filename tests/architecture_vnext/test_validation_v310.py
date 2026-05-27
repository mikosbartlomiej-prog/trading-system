"""v3.10 Phase E — validate_adaptation works at LLM_ENABLED=false + allows
intraday-safe deterministic adaptations (cooldown / size-cut / hard_safety disable)."""

import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import _path  # noqa: F401

import unittest
from datetime import datetime, timezone

from validation import validate_adaptation


def _state(strats):
    return {"strategies": strats, "last_validated_at": None}


def _stats(trades_by_strat):
    return {
        "by_strategy": {
            name: {"trades_7d": n} for name, n in trades_by_strat.items()
        }
    }


class TestValidationIntradaySafe(unittest.TestCase):
    def setUp(self):
        # Ensure we never accidentally read LLM-toggle env that might bias test
        os.environ.pop("LLM_ENABLED", None)

    def test_deterministic_cooldown_size_cut_allowed(self):
        """Size cut (down by 20%) is intraday-safe and should pass even with
        low sample (1 trade in 7d)."""
        old = _state({"strat-A": {"size_multiplier": 1.0, "enabled": True}})
        new = _state({"strat-A": {"size_multiplier": 0.8, "enabled": True}})
        stats = _stats({"strat-A": 1})
        r = validate_adaptation(old, new, stats)
        # 0.8 / 1.0 = 0.8 > 0.5 step-down threshold → accepted
        self.assertTrue(any("strat-A.size_multiplier" in a for a in r["accepted"]),
                        f"expected acceptance; got accepted={r['accepted']} rejected={r['rejected']}")

    def test_hard_safety_disable_passes_with_zero_sample(self):
        """5 consec losses pause uses hard_safety=True so validator must allow
        even when trades_7d < MIN_SAMPLE_DISABLE."""
        old = _state({"strat-X": {"enabled": True}})
        new = _state({"strat-X": {"enabled": False, "hard_safety": True,
                                  "paused_until": "2026-06-01"}})
        stats = _stats({"strat-X": 1})  # well below MIN_SAMPLE_DISABLE=10
        r = validate_adaptation(old, new, stats)
        # Must accept the disable
        accepted_strats = " ".join(r["accepted"])
        self.assertIn("strat-X.enabled True -> False", accepted_strats)
        self.assertFalse(r["validated_state"]["strategies"]["strat-X"]["enabled"])

    def test_disable_without_safety_blocked_at_low_sample(self):
        """Non-safety disable with insufficient sample → blocked (overfitting risk)."""
        old = _state({"strat-Y": {"enabled": True}})
        new = _state({"strat-Y": {"enabled": False}})  # no hard_safety
        stats = _stats({"strat-Y": 2})
        r = validate_adaptation(old, new, stats)
        self.assertTrue(any(rj["strategy"] == "strat-Y" for rj in r["rejected"]))
        # State reverted to enabled
        self.assertTrue(r["validated_state"]["strategies"]["strat-Y"]["enabled"])

    def test_aggressive_size_increase_blocked_low_sample(self):
        """Size UP without sample = overfitting; validator must block."""
        old = _state({"strat-Z": {"size_multiplier": 1.0}})
        new = _state({"strat-Z": {"size_multiplier": 1.4}})  # +40%
        stats = _stats({"strat-Z": 3})  # < MIN_SAMPLE_INCREASE=20
        r = validate_adaptation(old, new, stats)
        self.assertTrue(any(rj["strategy"] == "strat-Z" and rj["field"] == "size_multiplier"
                            for rj in r["rejected"]))
        # State reverted
        self.assertEqual(r["validated_state"]["strategies"]["strat-Z"]["size_multiplier"], 1.0)

    def test_validation_runs_without_llm_env(self):
        """Sanity: validate_adaptation never reads LLM_ENABLED — it operates
        purely on (old_state, new_state, today_stats)."""
        os.environ.pop("LLM_ENABLED", None)
        old = _state({"strat-Q": {"size_multiplier": 1.0}})
        new = _state({"strat-Q": {"size_multiplier": 0.9}})  # 10% cut, intraday safe
        r = validate_adaptation(old, new, _stats({"strat-Q": 5}))
        self.assertIsInstance(r, dict)
        self.assertIn("validated_state", r)
        self.assertIn("accepted", r)
        self.assertIn("rejected", r)


if __name__ == "__main__":
    unittest.main()
