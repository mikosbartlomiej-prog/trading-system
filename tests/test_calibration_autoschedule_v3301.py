"""v3.30.1 (2026-06-09) — calibration workflow is now self-gated.

The legacy ``vars.LLM_QUALITY_CALIBRATION_ENABLED`` repo variable
gate is removed. The workflow still:
  * keeps the daily cron schedule,
  * hard-pins all 7 broker-execution / live env flags ``"false"``,
  * runs the refusal step on truthy flags,
  * commits only LLM advisory + 6 doc paths (incl. the new
    repair status doc),
  * never calls submit_order / place_order / safe_close.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WF = (REPO_ROOT / ".github" / "workflows"
       / "llm-quality-calibration.yml")


class TestWorkflowSelfGated(unittest.TestCase):

    def setUp(self):
        self.assertTrue(WF.exists(),
                          "llm-quality-calibration.yml missing")
        self.src = WF.read_text(encoding="utf-8")

    def test_no_active_if_gate_on_enable_variable(self):
        """No ``if:`` line may reference LLM_QUALITY_CALIBRATION_ENABLED."""
        for line in self.src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if not stripped.startswith("if:"):
                continue
            self.assertNotIn(
                "LLM_QUALITY_CALIBRATION_ENABLED", stripped,
                f"unexpected enable-variable gate in active 'if:' "
                f"line: {line!r}")

    def test_cron_schedule_preserved(self):
        self.assertIsNotNone(
            re.search(r'cron:\s*"10 0 \* \* 1-5"', self.src))

    def test_all_broker_and_live_flags_pinned_false(self):
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

    def test_refusal_step_still_present(self):
        self.assertIn("REFUSED:", self.src)
        self.assertIn("exit 1", self.src)

    def test_commit_allow_list_includes_repair_artifacts(self):
        self.assertIn("docs/LLM_QUALITY_HISTORY_REPAIR_STATUS.md",
                       self.src)
        # And the existing allow-list paths still present.
        for p in (
            "learning-loop/llm_advisory/",
            "docs/LLM_ADVISORY_MESH_LATEST.md",
            "docs/LLM_ADVISORY_QUALITY_REVIEW.md",
            "docs/GEMINI_PROVIDER_STATUS.md",
            "docs/LLM_QUALITY_CALIBRATION_STATUS.md",
        ):
            self.assertIn(p, self.src,
                           f"workflow must allow committing {p}")

    def test_never_calls_order_placement(self):
        for forbidden in ("submit_order", "place_order",
                            "safe_close"):
            self.assertNotIn(forbidden, self.src)


if __name__ == "__main__":
    unittest.main()
