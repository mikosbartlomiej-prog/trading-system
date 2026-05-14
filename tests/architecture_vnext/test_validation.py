"""learning-loop/validation.py — sample-size + step-bound + once-per-day."""
import unittest
from datetime import datetime, timezone

import os, sys; sys.path.insert(0, os.path.dirname(__file__)); import _path  # noqa: F401

import validation


def stats(strategy: str, n_trades_7d: int) -> dict:
    return {"per_strategy": {strategy: {"trades_7d": n_trades_7d}}}


class TestValidationSampleSize(unittest.TestCase):
    def test_size_increase_blocked_low_sample(self):
        old = {"strategies": {"momentum": {"size_multiplier": 1.0}}}
        new = {"strategies": {"momentum": {"size_multiplier": 1.3}}}
        r = validation.validate_adaptation(old, new, stats("momentum", 5))
        self.assertEqual(r["validated_state"]["strategies"]["momentum"]["size_multiplier"], 1.0)
        self.assertTrue(any(x["field"] == "size_multiplier" for x in r["rejected"]))

    def test_size_increase_allowed_with_sample(self):
        old = {"strategies": {"momentum": {"size_multiplier": 1.0}}}
        new = {"strategies": {"momentum": {"size_multiplier": 1.3}}}
        r = validation.validate_adaptation(old, new, stats("momentum", 30))
        self.assertEqual(r["validated_state"]["strategies"]["momentum"]["size_multiplier"], 1.3)

    def test_size_decrease_always_allowed(self):
        # Reducing size (after losses) doesn't need a large sample.
        old = {"strategies": {"momentum": {"size_multiplier": 1.0}}}
        new = {"strategies": {"momentum": {"size_multiplier": 0.7}}}
        r = validation.validate_adaptation(old, new, stats("momentum", 3))
        self.assertEqual(r["validated_state"]["strategies"]["momentum"]["size_multiplier"], 0.7)

    def test_disable_blocked_low_sample_no_safety(self):
        old = {"strategies": {"momentum": {"enabled": True}}}
        new = {"strategies": {"momentum": {"enabled": False}}}
        r = validation.validate_adaptation(old, new, stats("momentum", 3))
        self.assertTrue(r["validated_state"]["strategies"]["momentum"]["enabled"])
        self.assertTrue(any(x["field"] == "enabled" for x in r["rejected"]))

    def test_disable_allowed_with_hard_safety_flag(self):
        old = {"strategies": {"momentum": {"enabled": True}}}
        new = {"strategies": {"momentum": {"enabled": False, "hard_safety": True}}}
        r = validation.validate_adaptation(old, new, stats("momentum", 3))
        self.assertFalse(r["validated_state"]["strategies"]["momentum"]["enabled"])

    def test_options_side_bias_requires_options_sample(self):
        old = {"strategies": {"options-momentum": {"side_bias": None}}}
        new = {"strategies": {"options-momentum": {"side_bias": "short"}}}
        r = validation.validate_adaptation(old, new, stats("options-momentum", 5))
        self.assertIsNone(r["validated_state"]["strategies"]["options-momentum"]["side_bias"])
        self.assertTrue(any(x["field"] == "side_bias" for x in r["rejected"]))


class TestValidationStepBounds(unittest.TestCase):
    def test_huge_step_up_blocked_even_with_sample(self):
        old = {"strategies": {"m": {"size_multiplier": 1.0}}}
        new = {"strategies": {"m": {"size_multiplier": 1.9}}}  # 1.9x = exceeds 1.5x daily
        r = validation.validate_adaptation(old, new, stats("m", 100))
        self.assertEqual(r["validated_state"]["strategies"]["m"]["size_multiplier"], 1.0)
        self.assertTrue(any("step-up" in x["reason"] for x in r["rejected"]))

    def test_huge_step_down_blocked(self):
        old = {"strategies": {"m": {"size_multiplier": 1.0}}}
        new = {"strategies": {"m": {"size_multiplier": 0.3}}}  # 0.3x < 0.5x daily min
        r = validation.validate_adaptation(old, new, stats("m", 100))
        self.assertEqual(r["validated_state"]["strategies"]["m"]["size_multiplier"], 1.0)


class TestValidationDoubleRun(unittest.TestCase):
    def test_already_validated_today_blocked(self):
        old = {"strategies": {"m": {"size_multiplier": 1.0}},
               "last_validated_at": datetime.now(timezone.utc).isoformat()}
        new = {"strategies": {"m": {"size_multiplier": 0.7}}}
        r = validation.validate_adaptation(old, new, stats("m", 50))
        self.assertTrue(r["second_run"])
        self.assertEqual(r["validated_state"]["strategies"]["m"]["size_multiplier"], 1.0)

    def test_allow_double_run_flag(self):
        old = {"strategies": {"m": {"size_multiplier": 1.0}},
               "last_validated_at": datetime.now(timezone.utc).isoformat()}
        new = {"strategies": {"m": {"size_multiplier": 0.7}}}
        r = validation.validate_adaptation(old, new, stats("m", 50), allow_double_run=True)
        self.assertFalse(r["second_run"])


if __name__ == "__main__":
    unittest.main()
