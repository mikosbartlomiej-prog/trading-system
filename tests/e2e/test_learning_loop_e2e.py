"""E2E: learning loop — validation + state policy + LLM fallback."""

import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import conftest  # noqa: F401

import unittest
from datetime import datetime, timezone

import validation
import state_policy
import state_schema
from tools.e2e_system_test_agent.fixtures import FakeLLM, FakeState


def stats(strategy: str, trades: int) -> dict:
    return {"per_strategy": {strategy: {"trades_7d": trades}}}


class TestLearningLoopValidation(unittest.TestCase):
    def test_size_increase_blocked_low_sample(self):
        old = {"strategies": {"momentum": {"size_multiplier": 1.0}}}
        new = {"strategies": {"momentum": {"size_multiplier": 1.3}}}
        r = validation.validate_adaptation(old, new, stats("momentum", 5))
        self.assertEqual(r["validated_state"]["strategies"]["momentum"]["size_multiplier"], 1.0)

    def test_size_increase_allowed_with_enough_sample(self):
        old = {"strategies": {"momentum": {"size_multiplier": 1.0}}}
        new = {"strategies": {"momentum": {"size_multiplier": 1.3}}}
        r = validation.validate_adaptation(old, new, stats("momentum", 30))
        self.assertEqual(r["validated_state"]["strategies"]["momentum"]["size_multiplier"], 1.3)

    def test_safety_disable_allowed_with_hard_flag(self):
        old = {"strategies": {"m": {"enabled": True}}}
        new = {"strategies": {"m": {"enabled": False, "hard_safety": True}}}
        r = validation.validate_adaptation(old, new, stats("m", 3))
        self.assertFalse(r["validated_state"]["strategies"]["m"]["enabled"])

    def test_once_per_day_rule(self):
        today = datetime.now(timezone.utc).isoformat()
        old = {"strategies": {"m": {"size_multiplier": 1.0}},
                "last_validated_at": today}
        new = {"strategies": {"m": {"size_multiplier": 0.7}}}
        r = validation.validate_adaptation(old, new, stats("m", 50))
        self.assertTrue(r["second_run"])


class TestStatePolicy(unittest.TestCase):
    def test_unknown_writer_rejected(self):
        with self.assertRaises(state_policy.StateWriteForbidden):
            state_policy.assert_can_write_state("price-monitor", "x")

    def test_daily_learning_allowed(self):
        actor = state_policy.assert_can_write_state("daily-learning", "x")
        self.assertEqual(actor, "daily-learning")


class TestStateSchemaValidation(unittest.TestCase):
    def test_hallucinated_keys_dropped(self):
        raw = {"strategies": {"m": {"delete_everything": True,
                                     "size_multiplier": 99.0,
                                     "enabled": "yes please"}}}
        sanitized, errors = state_schema.validate_state(raw)
        out = sanitized["strategies"]["m"]
        self.assertNotIn("delete_everything", out)
        self.assertNotIn("enabled", out)  # 'yes please' isn't a bool
        # Clamped to max
        self.assertEqual(out["size_multiplier"], state_schema.SIZE_MULT_MAX)
        self.assertTrue(errors)


class TestLLMFallback(unittest.TestCase):
    def test_disabled_llm_returns_none(self):
        llm = FakeLLM(mode="disabled")
        self.assertIsNone(llm.call())

    def test_timeout_llm_raises(self):
        llm = FakeLLM(mode="timeout")
        with self.assertRaises(TimeoutError):
            llm.call()

    def test_hallucinated_override_dropped_by_schema(self):
        llm = FakeLLM(mode="hallucinated")
        out = llm.call()
        sanitized, errors = state_schema.validate_state(out["state_overrides"])
        # Wormhole strategy was unknown; sanitized strategies dict has only
        # whatever survived. The hallucinated keys are all gone.
        for s in sanitized["strategies"].values():
            self.assertNotIn("delete_everything", s)
        self.assertTrue(errors)


class TestFakeStateUnauthorizedWriter(unittest.TestCase):
    def test_fake_state_blocks_unauthorized_writer(self):
        st = FakeState()
        with self.assertRaises(PermissionError):
            st.set(actor="price-monitor", reason="x",
                    mutator=lambda s: s)

    def test_fake_state_allows_daily_learning(self):
        st = FakeState()
        new = st.set(actor="daily-learning",
                      reason="size bump",
                      mutator=lambda s: {**s,
                                          "strategies": {**s["strategies"],
                                                         "aggressive-momentum": {
                                                             **s["strategies"]["aggressive-momentum"],
                                                             "size_multiplier": 1.1,
                                                         }}})
        self.assertEqual(new["last_writer"], "daily-learning")
        self.assertEqual(new["state_version"], 2)


if __name__ == "__main__":
    unittest.main()
