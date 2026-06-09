"""v3.28.2 (2026-06-09) — Gemini workflow YAML safety tests."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WF_PATH   = (REPO_ROOT / ".github" / "workflows"
              / "llm-advisory-mesh.yml")


class TestGeminiEnvPresent(unittest.TestCase):
    def test_gemini_api_key_secret_passed_through_env(self):
        text = WF_PATH.read_text(encoding="utf-8")
        self.assertIn("GEMINI_API_KEY:", text)
        self.assertIn("secrets.GEMINI_API_KEY", text)

    def test_gemini_model_default_set(self):
        # v3.29 switched the default to ``gemini-flash-latest`` (a
        # durable alias) and added a workflow_dispatch
        # ``model_override`` input that wins when set. Both shapes
        # must be present.
        text = WF_PATH.read_text(encoding="utf-8")
        self.assertIn("model_override", text)
        self.assertRegex(
            text,
            r"GEMINI_MODEL:\s*\$\{\{[^}]*"
            r"vars\.GEMINI_MODEL[^}]*"
            r"'gemini-flash-latest'[^}]*\}\}",
        )


class TestLlmFreeOnlyDefaultsTrue(unittest.TestCase):
    def test_free_only_defaults_true(self):
        text = WF_PATH.read_text(encoding="utf-8")
        self.assertRegex(
            text,
            r"LLM_FREE_ONLY:\s*\$\{\{\s*vars\.LLM_FREE_ONLY\s*\|\|\s*'true'\s*\}\}",
        )


class TestWorkflowHasNoBrokerSecrets(unittest.TestCase):
    def test_no_alpaca_secrets(self):
        text = WF_PATH.read_text(encoding="utf-8")
        for tok in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY",
                     "paper-api.alpaca.markets"):
            self.assertNotIn(tok, text)


class TestWorkflowBrokerFlagsPinnedFalse(unittest.TestCase):
    def test_seven_flags_pinned_false(self):
        text = WF_PATH.read_text(encoding="utf-8")
        for v in ("ALLOW_BROKER_PAPER", "EDGE_GATE_ENABLED",
                   "BROKER_EXECUTION_ENABLED",
                   "LIVE_TRADING", "LIVE_ENABLED", "GO_LIVE",
                   "LIVE_TRADING_ENABLED"):
            self.assertRegex(text, rf"{v}:\s*\"false\"")


class TestWorkflowScheduleStillGated(unittest.TestCase):
    def test_schedule_gated_on_repo_var(self):
        text = WF_PATH.read_text(encoding="utf-8")
        self.assertIn("LLM_AGENTS_SCHEDULED", text)
        self.assertIn(
            "vars.LLM_AGENTS_SCHEDULED == 'true'", text)


class TestProviderDefaultsOfflineMock(unittest.TestCase):
    def test_provider_default(self):
        text = WF_PATH.read_text(encoding="utf-8")
        self.assertRegex(
            text,
            r"LLM_PROVIDER:\s*\$\{\{\s*vars\.LLM_PROVIDER\s*\|\|\s*'offline_mock'\s*\}\}",
        )

    def test_llm_agents_enabled_defaults_false(self):
        text = WF_PATH.read_text(encoding="utf-8")
        self.assertRegex(
            text,
            r"LLM_AGENTS_ENABLED:\s*\$\{\{\s*vars\.LLM_AGENTS_ENABLED\s*\|\|\s*'false'\s*\}\}",
        )


class TestNoBrokerOrderReference(unittest.TestCase):
    def test_no_broker_module_ref(self):
        text = WF_PATH.read_text(encoding="utf-8")
        for tok in ("alpaca_orders", "place_stock_bracket",
                     "place_crypto_order"):
            self.assertNotIn(tok, text)


if __name__ == "__main__":
    unittest.main()
