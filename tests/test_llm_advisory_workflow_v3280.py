"""v3.28 (2026-06-09) — workflow YAML safety tests."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WF_PATH   = (REPO_ROOT / ".github" / "workflows"
              / "llm-advisory-mesh.yml")


class TestWorkflowExists(unittest.TestCase):
    def test_exists(self):
        self.assertTrue(WF_PATH.exists())


class TestWorkflowHasNoBrokerSecrets(unittest.TestCase):
    def test_no_alpaca_in_yaml(self):
        text = WF_PATH.read_text(encoding="utf-8")
        for tok in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY",
                     "paper-api.alpaca.markets"):
            self.assertNotIn(tok, text,
                              f"broker token in v3.28 workflow: {tok}")


class TestWorkflowBrokerFlagsPinned(unittest.TestCase):
    def test_seven_flags_pinned_false(self):
        text = WF_PATH.read_text(encoding="utf-8")
        for v in ("ALLOW_BROKER_PAPER", "EDGE_GATE_ENABLED",
                   "BROKER_EXECUTION_ENABLED",
                   "LIVE_TRADING", "LIVE_ENABLED", "GO_LIVE",
                   "LIVE_TRADING_ENABLED"):
            self.assertRegex(
                text, rf"{v}:\s*\"false\"",
                f"{v} not pinned false in workflow")


class TestWorkflowDispatchDefault(unittest.TestCase):
    def test_workflow_dispatch_enabled(self):
        text = WF_PATH.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)

    def test_schedule_gated_on_repo_var(self):
        text = WF_PATH.read_text(encoding="utf-8")
        # The schedule path runs only when LLM_AGENTS_SCHEDULED=true.
        self.assertIn("LLM_AGENTS_SCHEDULED", text)


class TestWorkflowDefaultEnvSafe(unittest.TestCase):
    def test_llm_agents_enabled_defaults_false(self):
        text = WF_PATH.read_text(encoding="utf-8")
        self.assertRegex(
            text,
            r"LLM_AGENTS_ENABLED:\s*\$\{\{\s*vars\.LLM_AGENTS_ENABLED\s*\|\|\s*'false'\s*\}\}",
        )

    def test_provider_defaults_offline_mock(self):
        text = WF_PATH.read_text(encoding="utf-8")
        self.assertRegex(
            text,
            r"LLM_PROVIDER:\s*\$\{\{\s*vars\.LLM_PROVIDER\s*\|\|\s*'offline_mock'\s*\}\}",
        )


class TestWorkflowAllowList(unittest.TestCase):
    def test_path_allow_list_present(self):
        text = WF_PATH.read_text(encoding="utf-8")
        # The path-check step must list exactly the three approved
        # commit paths.
        self.assertIn("learning-loop/llm_advisory/", text)
        self.assertIn("docs/LLM_ADVISORY_MESH_LATEST.md", text)
        self.assertIn(
            "learning-loop/position_reconciliation/latest.json", text)

    def test_refuses_unauthorized_paths(self):
        text = WF_PATH.read_text(encoding="utf-8")
        self.assertIn("REFUSED: unauthorized paths in staged diff",
                       text)


class TestWorkflowNeverImportsBrokerOrders(unittest.TestCase):
    def test_workflow_does_not_reference_broker_module(self):
        text = WF_PATH.read_text(encoding="utf-8")
        for tok in ("alpaca_orders", "safe_close",
                     "place_stock_bracket", "place_crypto_order"):
            self.assertNotIn(tok, text)


if __name__ == "__main__":
    unittest.main()
