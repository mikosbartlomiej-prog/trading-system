"""v3.30 (2026-06-09) — signal-shadow workflow safety contract."""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WF = REPO_ROOT / ".github" / "workflows" / "signal-shadow-evidence.yml"


class TestWorkflowEnvHardPins(unittest.TestCase):

    def setUp(self):
        self.assertTrue(WF.exists())
        self.src = WF.read_text(encoding="utf-8")

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
            self.assertIn(f'{flag}: "false"', self.src,
                           f"{flag} must be pinned to \"false\"")

    def test_workflow_never_calls_submit_or_place_or_close(self):
        for forbidden in ("submit_order", "place_order",
                            "safe_close"):
            self.assertNotIn(forbidden, self.src,
                              f"workflow must NOT contain {forbidden}")

    def test_workflow_calls_shadow_evidence_collector(self):
        self.assertIn(
            "run_signal_shadow_evidence_collection.py",
            self.src,
            "workflow must invoke the shadow-evidence collector")


class TestWorkflowRefusalGuard(unittest.TestCase):

    def test_refuse_step_present_for_broker_flags(self):
        src = WF.read_text(encoding="utf-8")
        self.assertIn("BROKER_EXECUTION_ENABLED", src)
        # The workflow includes a guard step that exits non-zero if
        # any of the broker/live flags are truthy.
        self.assertIn("REFUSED:", src,
                       "workflow must include the truthy-flag refusal "
                       "loop that prints REFUSED: <flag>")
        self.assertIn("exit 1", src,
                       "workflow must exit non-zero on a truthy flag")


if __name__ == "__main__":
    unittest.main()
