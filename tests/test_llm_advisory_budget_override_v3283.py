"""v3.28.3 (2026-06-09) — per-run budget override tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestNoOverrideKeepsDefault(unittest.TestCase):
    def test_default_is_5(self):
        import llm_agent_budget as b
        with mock.patch.dict(os.environ, {
            "LLM_AGENT_PER_RUN_BUDGET":          "",
            "LLM_AGENT_PER_RUN_BUDGET_OVERRIDE": "",
        }, clear=False):
            os.environ.pop("LLM_AGENT_PER_RUN_BUDGET", None)
            os.environ.pop("LLM_AGENT_PER_RUN_BUDGET_OVERRIDE", None)
            self.assertEqual(b.per_run_budget(), 5)


class TestOverrideOnlyWithGeminiAndFreeOnly(unittest.TestCase):
    def test_override_honoured_with_gemini_and_free_only(self):
        import llm_agent_budget as b
        with mock.patch.dict(os.environ, {
            "LLM_AGENT_PER_RUN_BUDGET_OVERRIDE": "11",
            "LLM_PROVIDER":   "gemini",
            "LLM_FREE_ONLY":  "true",
        }, clear=False):
            self.assertEqual(b.per_run_budget(), 11)

    def test_override_ignored_when_provider_is_anthropic(self):
        import llm_agent_budget as b
        with mock.patch.dict(os.environ, {
            "LLM_AGENT_PER_RUN_BUDGET_OVERRIDE": "11",
            "LLM_PROVIDER":   "anthropic",
            "LLM_FREE_ONLY":  "true",
        }, clear=False):
            # Stays at base default 5.
            self.assertEqual(b.per_run_budget(), 5)

    def test_override_ignored_when_free_only_off(self):
        import llm_agent_budget as b
        with mock.patch.dict(os.environ, {
            "LLM_AGENT_PER_RUN_BUDGET_OVERRIDE": "11",
            "LLM_PROVIDER":   "gemini",
            "LLM_FREE_ONLY":  "false",
        }, clear=False):
            self.assertEqual(b.per_run_budget(), 5)

    def test_override_ignored_when_provider_is_openai(self):
        import llm_agent_budget as b
        with mock.patch.dict(os.environ, {
            "LLM_AGENT_PER_RUN_BUDGET_OVERRIDE": "11",
            "LLM_PROVIDER":   "openai",
            "LLM_FREE_ONLY":  "true",
        }, clear=False):
            self.assertEqual(b.per_run_budget(), 5)


class TestOverrideClampedTo11(unittest.TestCase):
    def test_clamped_high(self):
        import llm_agent_budget as b
        with mock.patch.dict(os.environ, {
            "LLM_AGENT_PER_RUN_BUDGET_OVERRIDE": "999",
            "LLM_PROVIDER":   "gemini",
            "LLM_FREE_ONLY":  "true",
        }, clear=False):
            self.assertEqual(b.per_run_budget(), 11)

    def test_clamped_low(self):
        import llm_agent_budget as b
        with mock.patch.dict(os.environ, {
            "LLM_AGENT_PER_RUN_BUDGET_OVERRIDE": "-5",
            "LLM_PROVIDER":   "gemini",
            "LLM_FREE_ONLY":  "true",
        }, clear=False):
            self.assertEqual(b.per_run_budget(), 1)


class TestOverrideAcceptsValidIntermediates(unittest.TestCase):
    def test_seven_honoured(self):
        import llm_agent_budget as b
        with mock.patch.dict(os.environ, {
            "LLM_AGENT_PER_RUN_BUDGET_OVERRIDE": "7",
            "LLM_PROVIDER":   "gemini",
            "LLM_FREE_ONLY":  "true",
        }, clear=False):
            self.assertEqual(b.per_run_budget(), 7)


class TestOverrideMalformedFallsBack(unittest.TestCase):
    def test_non_int_falls_back_to_default(self):
        import llm_agent_budget as b
        with mock.patch.dict(os.environ, {
            "LLM_AGENT_PER_RUN_BUDGET_OVERRIDE": "abc",
            "LLM_PROVIDER":   "gemini",
            "LLM_FREE_ONLY":  "true",
        }, clear=False):
            self.assertEqual(b.per_run_budget(), 5)


class TestWorkflowInputPresent(unittest.TestCase):
    def test_workflow_yaml_has_input(self):
        path = REPO_ROOT / ".github" / "workflows" / "llm-advisory-mesh.yml"
        text = path.read_text(encoding="utf-8")
        self.assertIn("per_run_budget_override:", text)
        self.assertIn("LLM_AGENT_PER_RUN_BUDGET_OVERRIDE:", text)
        # Schedule still gated.
        self.assertIn("LLM_AGENTS_SCHEDULED == 'true'", text)


if __name__ == "__main__":
    unittest.main()
