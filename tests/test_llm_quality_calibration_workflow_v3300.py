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

    def test_scheduled_run_self_gated_no_manual_variable_required(self):
        """v3.30.1 contract: the workflow is self-gated. The legacy
        ``LLM_QUALITY_CALIBRATION_ENABLED`` repo variable is NOT
        required. The optional opt-out is
        ``LLM_QUALITY_CALIBRATION_DISABLED``.
        """
        import re
        # The old enable gate must not appear in an active 'if:' line.
        for line in self.src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if not stripped.startswith("if:"):
                continue
            self.assertNotIn(
                "LLM_QUALITY_CALIBRATION_ENABLED", stripped,
                "v3.30.1: workflow must NOT gate on "
                "LLM_QUALITY_CALIBRATION_ENABLED in any 'if:' block")
        # Workflow still must reference the cron schedule.
        self.assertIsNotNone(
            re.search(r'cron:\s*"10 0 \* \* 1-5"', self.src),
            "calibration cron schedule must still be present")

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
        # v3.30.1 — 8 status enum (DISABLED is now DISABLED_BY_OPERATOR).
        for status in (
            "CALIBRATION_PROCEEDING",
            "CALIBRATION_SKIPPED_ALREADY_CALIBRATED",
            "CALIBRATION_SKIPPED_DISABLED_BY_OPERATOR",
            "CALIBRATION_SKIPPED_BUDGET_EXHAUSTED",
        ):
            self.assertIn(status, src,
                           f"precheck must expose {status}")
        # Never calls / imports order placement. Allowed to MENTION
        # the forbidden symbols in safety comments / docstrings.
        import ast
        tree = ast.parse(src)
        forbidden_imports = {"alpaca_orders"}
        forbidden_calls = {"submit_order", "place_order",
                              "safe_close"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(
                        alias.name.split(".")[-1],
                        forbidden_imports)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.assertNotIn(
                        node.module.split(".")[-1],
                        forbidden_imports)
                for alias in node.names:
                    self.assertNotIn(
                        alias.name, forbidden_imports)
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    self.assertNotIn(func.id, forbidden_calls)
                elif isinstance(func, ast.Attribute):
                    self.assertNotIn(func.attr, forbidden_calls)


if __name__ == "__main__":
    unittest.main()
