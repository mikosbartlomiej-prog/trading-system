"""state_policy + state_schema — only authorized writers; malformed rejected."""
import os
import unittest
from unittest import mock

import os, sys; sys.path.insert(0, os.path.dirname(__file__)); import _path  # noqa: F401

import state_policy
import state_schema


class TestStatePolicy(unittest.TestCase):
    def test_unknown_actor_cannot_write(self):
        with mock.patch.dict(os.environ, {"STATE_WRITE_ACTOR": "price-monitor"}):
            self.assertFalse(state_policy.can_write_state())

    def test_daily_learning_can_write(self):
        with mock.patch.dict(os.environ, {"STATE_WRITE_ACTOR": "daily-learning"}):
            self.assertTrue(state_policy.can_write_state())

    def test_assert_can_write_raises_for_unknown(self):
        with self.assertRaises(state_policy.StateWriteForbidden):
            state_policy.assert_can_write_state("exit-monitor", "trying to persist peak")

    def test_assert_can_write_returns_canonical_name(self):
        actor = state_policy.assert_can_write_state("Daily-Learning", "applied 3 overrides")
        self.assertEqual(actor, "daily-learning")

    def test_stamp_metadata_increments_version_and_stamps_audit(self):
        state = {}
        state_policy.stamp_state_metadata(state, "daily-learning", "first write")
        self.assertEqual(state["state_version"], 1)
        self.assertEqual(state["last_writer"], "daily-learning")
        self.assertEqual(state["last_write_reason"], "first write")
        self.assertIn("T", state["last_validated_at"])  # ISO format
        # Idempotent increment
        state_policy.stamp_state_metadata(state, "daily-learning", "second write")
        self.assertEqual(state["state_version"], 2)

    def test_explicit_param_beats_env(self):
        with mock.patch.dict(os.environ, {"STATE_WRITE_ACTOR": "price-monitor"}):
            self.assertTrue(state_policy.can_write_state("daily-learning"))


class TestStateSchema(unittest.TestCase):
    def test_size_multiplier_clamped(self):
        raw = {"strategies": {"options-momentum": {"size_multiplier": 99.0}}}
        out, errs = state_schema.validate_state(raw)
        self.assertEqual(out["strategies"]["options-momentum"]["size_multiplier"],
                         state_schema.SIZE_MULT_MAX)
        self.assertTrue(any("clamped" in e for e in errs))

    def test_size_multiplier_lower_clamp(self):
        raw = {"strategies": {"momentum": {"size_multiplier": 0.0}}}
        out, _ = state_schema.validate_state(raw)
        self.assertEqual(out["strategies"]["momentum"]["size_multiplier"],
                         state_schema.SIZE_MULT_MIN)

    def test_enabled_non_bool_dropped(self):
        raw = {"strategies": {"momentum": {"enabled": "yes please"}}}
        out, errs = state_schema.validate_state(raw)
        self.assertNotIn("enabled", out["strategies"].get("momentum", {}))
        self.assertTrue(any("not boolean" in e for e in errs))

    def test_side_bias_invalid_dropped(self):
        raw = {"strategies": {"options-momentum": {"side_bias": "neither"}}}
        out, errs = state_schema.validate_state(raw)
        self.assertNotIn("side_bias", out["strategies"].get("options-momentum", {}))
        self.assertTrue(any("side_bias" in e for e in errs))

    def test_unknown_fields_dropped(self):
        raw = {"strategies": {"momentum": {"delete_everything": True, "size_multiplier": 1.0}}}
        out, errs = state_schema.validate_state(raw)
        self.assertNotIn("delete_everything", out["strategies"]["momentum"])
        self.assertEqual(out["strategies"]["momentum"]["size_multiplier"], 1.0)
        self.assertTrue(any("unknown fields" in e for e in errs))

    def test_paused_until_iso_date_accepted(self):
        raw = {"strategies": {"momentum": {"paused_until": "2026-06-01"}}}
        out, errs = state_schema.validate_state(raw)
        self.assertEqual(out["strategies"]["momentum"]["paused_until"], "2026-06-01")
        # Allowed value, no errors expected
        self.assertEqual([e for e in errs if "paused_until" in e], [])

    def test_paused_until_bad_date_dropped(self):
        raw = {"strategies": {"momentum": {"paused_until": "tomorrow"}}}
        out, errs = state_schema.validate_state(raw)
        self.assertNotIn("paused_until", out["strategies"].get("momentum", {}))
        self.assertTrue(any("paused_until" in e for e in errs))

    def test_state_not_a_dict(self):
        out, errs = state_schema.validate_state("not a state")
        self.assertEqual(out, {"strategies": {}})
        self.assertTrue(errs)

    def test_notes_truncated(self):
        big = "x" * 5000
        raw = {"strategies": {"m": {"notes": big}}}
        out, _ = state_schema.validate_state(raw)
        self.assertEqual(len(out["strategies"]["m"]["notes"]), state_schema.NOTES_MAX_LEN)

    def test_is_valid_passes_on_clean(self):
        raw = {"strategies": {"m": {"size_multiplier": 1.2, "enabled": True}}}
        self.assertTrue(state_schema.is_valid(raw))

    def test_is_valid_fails_on_dirty(self):
        raw = {"strategies": {"m": {"size_multiplier": "much"}}}
        self.assertFalse(state_schema.is_valid(raw))


if __name__ == "__main__":
    unittest.main()
