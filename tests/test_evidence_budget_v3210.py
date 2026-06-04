"""v3.21.0 (2026-06-04) — Tests for shared/evidence_budget.py."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime_path = Path(self.tmp.name) / "runtime_state.json"
        os.environ["RUNTIME_STATE_PATH"] = str(self.runtime_path)
        os.environ.pop("EVIDENCE_BUDGET_STRATEGY", None)

        # Force fresh imports so module-level paths re-resolve.
        for k in list(sys.modules):
            if k in ("evidence_budget", "runtime_state",
                     "state_policy") \
               or k.endswith(".evidence_budget") \
               or k.endswith(".runtime_state") \
               or k.endswith(".state_policy"):
                del sys.modules[k]

        import evidence_budget as eb  # noqa: WPS433
        self.eb = eb

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("RUNTIME_STATE_PATH", None)
        os.environ.pop("EVIDENCE_BUDGET_STRATEGY", None)


class TestPerDayCaps(_Base):

    def test_shadow_observation_within_cap_allowed(self):
        allowed, reason = self.eb.check_budget("shadow_observation", 1)
        self.assertTrue(allowed)
        self.assertIn("per_day_ok", reason)

    def test_shadow_observation_cap_blocks(self):
        # Push to the cap.
        allowed, _ = self.eb.check_budget(
            "shadow_observation",
            self.eb.MAX_SHADOW_OBS_PER_DAY,
        )
        self.assertTrue(allowed)
        # One more is denied.
        allowed2, reason = self.eb.check_budget("shadow_observation", 1)
        self.assertFalse(allowed2)
        self.assertIn("per_day_limit", reason)


class TestVariantCap(_Base):

    def test_budget_caps_variants(self):
        allowed, _ = self.eb.check_budget(
            "variant_evaluation",
            self.eb.MAX_VARIANTS_EVALUATED_PER_DAY,
        )
        self.assertTrue(allowed)
        allowed2, reason = self.eb.check_budget("variant_evaluation", 1)
        self.assertFalse(allowed2)
        self.assertIn("per_day_limit", reason)


class TestSafetyBypass(_Base):
    """Spec invariant: budget NEVER suppresses safety reports."""

    def test_invariant_constant_true(self):
        self.assertTrue(self.eb.BUDGET_BYPASSES_SAFETY)

    def test_safety_report_always_allowed(self):
        # Exhaust the shadow_observation budget completely first.
        self.eb.check_budget("shadow_observation",
                             self.eb.MAX_SHADOW_OBS_PER_DAY)
        # Safety reports still pass through.
        allowed, reason = self.eb.check_budget("safety_report", 1)
        self.assertTrue(allowed)
        self.assertIn("safety_action", reason)

    def test_kill_switch_alert_always_allowed(self):
        allowed, reason = self.eb.check_budget("kill_switch_alert", 1)
        self.assertTrue(allowed)
        self.assertIn("safety_action", reason)

    def test_safe_mode_transition_always_allowed(self):
        allowed, _ = self.eb.check_budget("safe_mode_transition", 1)
        self.assertTrue(allowed)


class TestDeterminism(_Base):
    """Same input -> same (allowed, reason)."""

    def test_two_clean_runs_match(self):
        # Fresh state for run A.
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["RUNTIME_STATE_PATH"] = str(
            Path(self.tmp.name) / "runtime_state.json"
        )
        # Reset env to ensure clean state for run A.
        for k in list(sys.modules):
            if k in ("evidence_budget", "runtime_state") \
               or k.endswith(".evidence_budget") \
               or k.endswith(".runtime_state"):
                del sys.modules[k]
        import evidence_budget as ebA  # noqa: WPS433
        a = ebA.check_budget("counterfactual_run", 10)

        # Fresh state for run B.
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["RUNTIME_STATE_PATH"] = str(
            Path(self.tmp.name) / "runtime_state.json"
        )
        for k in list(sys.modules):
            if k in ("evidence_budget", "runtime_state") \
               or k.endswith(".evidence_budget") \
               or k.endswith(".runtime_state"):
                del sys.modules[k]
        import evidence_budget as ebB  # noqa: WPS433
        b = ebB.check_budget("counterfactual_run", 10)

        self.assertEqual(a, b)


class TestReportGenerated(_Base):

    def test_report_renderable(self):
        # Consume some budget to get a non-trivial report.
        self.eb.check_budget("shadow_observation", 3)
        os.environ["EVIDENCE_BUDGET_STRATEGY"] = "strat-x"
        self.eb.check_budget("symbol_for_strategy", 2)
        md = self.eb.render_report()
        self.assertIn("Evidence Budget", md)
        self.assertIn("BUDGET_BYPASSES_SAFETY: True", md)
        self.assertIn("shadow_observation", md)
        self.assertIn("strat-x", md)


class TestUnknownAndPerStrategy(_Base):

    def test_unknown_action_type_denied(self):
        allowed, reason = self.eb.check_budget("rocket_launch", 1)
        self.assertFalse(allowed)
        self.assertTrue(reason.startswith("unknown_action_type:"))

    def test_per_strategy_cap_uses_env(self):
        os.environ["EVIDENCE_BUDGET_STRATEGY"] = "alpha"
        allowed, _ = self.eb.check_budget(
            "symbol_for_strategy",
            self.eb.MAX_SYMBOLS_PER_STRATEGY,
        )
        self.assertTrue(allowed)
        allowed2, reason = self.eb.check_budget(
            "symbol_for_strategy", 1
        )
        self.assertFalse(allowed2)
        self.assertIn("per_strategy_limit", reason)
        self.assertIn("alpha", reason)


class TestResetRunCounters(_Base):

    def test_reset_run_clears_per_run_only(self):
        # Push per-day + per-run.
        self.eb.check_budget("shadow_observation", 5)
        self.eb.check_budget("counterfactual_run", 5)
        self.eb.reset_run_counters()
        s = self.eb.get_state()
        # Per-day untouched, per-run reset.
        self.assertEqual(s.get("shadow_observation"), 5)
        self.assertEqual(s.get("counterfactual_run"), 0)


if __name__ == "__main__":
    unittest.main()
