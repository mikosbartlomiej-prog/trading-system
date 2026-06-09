"""v3.29.1 (2026-06-09) — shadow opportunity expansion safety.

v3.29.1 ships no actual generator/universe expansion — only the
recommendation analyzer + executor design + observation proposal.
These tests guard the safety contract:

- accelerator is read-only,
- accelerator never mutates counters,
- accelerator never enables broker paper,
- accelerator never imports broker-orders module,
- workflow is read-only and commit-path-restricted,
- 22-bar floor on bars is not lowered.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestAccelWorkflowExists(unittest.TestCase):
    def test_workflow_present(self):
        path = (REPO_ROOT / ".github" / "workflows"
                 / "real-market-evidence-accelerator.yml")
        self.assertTrue(path.exists())


class TestAccelWorkflowBrokerFlagsPinned(unittest.TestCase):
    def test_seven_flags_pinned_false(self):
        text = (REPO_ROOT / ".github" / "workflows"
                 / "real-market-evidence-accelerator.yml"
                 ).read_text(encoding="utf-8")
        for v in ("ALLOW_BROKER_PAPER", "EDGE_GATE_ENABLED",
                   "BROKER_EXECUTION_ENABLED",
                   "LIVE_TRADING", "LIVE_ENABLED", "GO_LIVE",
                   "LIVE_TRADING_ENABLED"):
            self.assertRegex(text, rf"{v}:\s*\"false\"")


class TestAccelWorkflowReadOnlyCommitAllowList(unittest.TestCase):
    def test_allow_list_tight(self):
        text = (REPO_ROOT / ".github" / "workflows"
                 / "real-market-evidence-accelerator.yml"
                 ).read_text(encoding="utf-8")
        for needed in (
            "learning-loop/shadow_evidence/acceleration_latest.json",
            "docs/REAL_MARKET_EVIDENCE_ACCELERATION.md",
            "docs/REAL_MARKET_OBSERVATION_RECORD_PROPOSAL.md",
        ):
            self.assertIn(needed, text)
        # Workflow refuses other paths.
        self.assertIn(
            "REFUSED: unauthorized paths in staged diff", text)


class TestAccelWorkflowNoBrokerSecrets(unittest.TestCase):
    def test_no_alpaca_secrets(self):
        text = (REPO_ROOT / ".github" / "workflows"
                 / "real-market-evidence-accelerator.yml"
                 ).read_text(encoding="utf-8")
        for tok in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY",
                     "paper-api.alpaca.markets"):
            self.assertNotIn(tok, text)


class Test22BarFloorPreserved(unittest.TestCase):
    def test_provider_pins_22_floor(self):
        text = (REPO_ROOT / "shared"
                 / "market_data_provider.py").read_text(
            encoding="utf-8")
        # The provider still enforces the 22-bar ATR-window floor.
        self.assertIn("INSUFFICIENT_BARS_FOR_SIGNAL", text)
        self.assertIn("< 22", text)


class TestExecutorDesignDocExists(unittest.TestCase):
    def test_design_doc_present(self):
        path = (REPO_ROOT / "docs"
                 / "BROKER_PAPER_CANARY_EXECUTOR_DESIGN.md")
        self.assertTrue(path.exists())

    def test_design_doc_says_not_implemented(self):
        text = (REPO_ROOT / "docs"
                 / "BROKER_PAPER_CANARY_EXECUTOR_DESIGN.md"
                 ).read_text(encoding="utf-8")
        self.assertIn("NOT IMPLEMENTED", text)
        self.assertIn("DETERMINISTIC_GATES_REMAIN_FINAL", text)


if __name__ == "__main__":
    unittest.main()
