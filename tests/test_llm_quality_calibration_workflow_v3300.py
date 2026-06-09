"""v3.30 (2026-06-09) — bounded Gemini calibration workflow contract.

This test verifies the static structure of the calibration workflow:
- All 7 broker-execution / live env flags hard-pinned ``"false"``.
- Scheduled trigger gated on the ``LLM_QUALITY_CALIBRATION_ENABLED``
  repo variable.
- A "REFUSED" guard step rejects truthy flags.
- A precheck step early-exits when calibration is already complete or
  the daily Gemini budget is exhausted.
- Commit allow-list contains ONLY LLM advisory + 4 doc paths.
- Workflow NEVER calls submit_order / place_order / safe_close.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WF = (REPO_ROOT / ".github" / "workflows"
       / "llm-quality-calibration.yml")


class TestCalibrationWorkflowSafety(unittest.TestCase):

    def setUp(self):
        self.assertTrue(WF.exists(),
                          "llm-quality-calibration.yml missing")
        self.src = WF.read_text(encoding="utf-8")

    def test_all_broker_and_live_flags_pinned_false(self):
        import re
        for flag in (
            "ALLOW_BROKER_PAPER",
            "EDGE_GATE_ENABLED",
            "BROKER_EXECUTION_ENABLED",
            "LIVE_TRADING",
            "LIVE_ENABLED",
            "GO_LIVE",
            "LIVE_TRADING_ENABLED",
        ):
            self.assertIsNotNone(
                re.search(rf'\n\s*{flag}:\s+"false"', self.src),
                f"{flag} must be pinned to \"false\"")

    def test_scheduled_run_gated_on_repo_variable(self):
        self.assertIn("LLM_QUALITY_CALIBRATION_ENABLED", self.src)
        self.assertIn("vars.LLM_QUALITY_CALIBRATION_ENABLED",
                       self.src)

    def test_refuse_step_present(self):
        self.assertIn("REFUSED:", self.src)
        self.assertIn("exit 1", self.src)

    def test_precheck_step_present(self):
        self.assertIn("llm_quality_calibration_precheck.py",
                       self.src)
        self.assertIn("CALIBRATION_PROCEEDING", self.src)

    def test_commit_allow_list_present(self):
        self.assertIn("learning-loop/llm_advisory/", self.src)
        self.assertIn("docs/LLM_ADVISORY_MESH_LATEST.md", self.src)
        self.assertIn("docs/LLM_ADVISORY_QUALITY_REVIEW.md", self.src)
        self.assertIn("docs/GEMINI_PROVIDER_STATUS.md", self.src)
        self.assertIn("docs/LLM_QUALITY_CALIBRATION_STATUS.md",
                       self.src)

    def test_never_calls_order_placement(self):
        for forbidden in ("submit_order", "place_order",
                            "safe_close"):
            self.assertNotIn(forbidden, self.src)


class TestCalibrationPrecheckScript(unittest.TestCase):

    def test_precheck_module_imports_and_exposes_statuses(self):
        script = (REPO_ROOT / "scripts"
                   / "llm_quality_calibration_precheck.py")
        self.assertTrue(script.exists(),
                          "calibration precheck script missing")
        src = script.read_text(encoding="utf-8")
        for status in (
            "CALIBRATION_PROCEEDING",
            "CALIBRATION_SKIPPED_ALREADY_CALIBRATED",
            "CALIBRATION_SKIPPED_DISABLED",
            "CALIBRATION_SKIPPED_BUDGET_EXHAUSTED",
        ):
            self.assertIn(status, src,
                           f"precheck must expose {status}")
        # Never calls order placement.
        for forbidden in ("submit_order", "place_order",
                            "safe_close", "alpaca_orders"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
