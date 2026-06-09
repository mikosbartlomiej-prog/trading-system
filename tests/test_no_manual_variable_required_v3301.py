"""v3.30.1 (2026-06-09) — no manual repo variable required.

Static contract: the calibration workflow no longer requires a
manually-set ``LLM_QUALITY_CALIBRATION_ENABLED`` repo variable. The
optional operator opt-out is ``LLM_QUALITY_CALIBRATION_DISABLED``.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WF = (REPO_ROOT / ".github" / "workflows"
       / "llm-quality-calibration.yml")
PRECHECK = (REPO_ROOT / "scripts"
             / "llm_quality_calibration_precheck.py")


class TestWorkflowNoActiveEnableGate(unittest.TestCase):
    def test_enable_variable_not_in_active_if_line(self):
        self.assertTrue(WF.exists())
        for line in WF.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if not stripped.startswith("if:"):
                continue
            self.assertNotIn(
                "LLM_QUALITY_CALIBRATION_ENABLED", stripped,
                "v3.30.1: workflow must not gate on enable variable")


class TestPrecheckScript(unittest.TestCase):
    def test_precheck_does_not_require_enable_variable(self):
        """Precheck must NOT actively READ
        ``LLM_QUALITY_CALIBRATION_ENABLED`` (it is allowed to be
        mentioned in a docstring / comment as historical context).
        """
        import ast
        self.assertTrue(PRECHECK.exists())
        src = PRECHECK.read_text(encoding="utf-8")
        tree = ast.parse(src)
        # Walk every Call node; flag if it reads the legacy variable.
        bad = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Either os.environ.get("LLM_QUALITY_CALIBRATION_ENABLED")
            # or _env_truthy("LLM_QUALITY_CALIBRATION_ENABLED").
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(
                        arg.value, str) and arg.value == (
                            "LLM_QUALITY_CALIBRATION_ENABLED"):
                    bad.append(ast.dump(node))
        self.assertEqual(
            bad, [],
            "precheck must NOT actively read the legacy enable "
            f"variable; found: {bad}")

    def test_precheck_accepts_disabled_opt_out(self):
        """Precheck must read ``LLM_QUALITY_CALIBRATION_DISABLED``."""
        self.assertTrue(PRECHECK.exists())
        src = PRECHECK.read_text(encoding="utf-8")
        self.assertIn("LLM_QUALITY_CALIBRATION_DISABLED", src)


if __name__ == "__main__":
    unittest.main()
