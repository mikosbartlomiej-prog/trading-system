"""v3.28.2 (2026-06-09) — free-only policy tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestFreeOnlyDefaultsTrue(unittest.TestCase):
    def test_default_blocks_anthropic(self):
        import llm_provider_client as p
        with mock.patch.dict(os.environ, {
            "LLM_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "x",
            "LLM_FREE_ONLY": "",  # explicitly empty → use default
        }, clear=False):
            os.environ.pop("LLM_FREE_ONLY", None)
            resp = p.call_provider(prompt="hi")
            self.assertEqual(
                resp.status, p.LLM_PROVIDER_BLOCKED_BY_FREE_ONLY)

    def test_default_blocks_openai(self):
        import llm_provider_client as p
        with mock.patch.dict(os.environ, {
            "LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "x",
        }, clear=False):
            os.environ.pop("LLM_FREE_ONLY", None)
            resp = p.call_provider(prompt="hi")
            self.assertEqual(
                resp.status, p.LLM_PROVIDER_BLOCKED_BY_FREE_ONLY)

    def test_free_only_true_allows_gemini_when_key_missing(self):
        # Free-only=true does NOT block Gemini — but missing key
        # routes to LLM_PROVIDER_KEY_MISSING (still a non-paid path).
        import llm_provider_client as p
        with mock.patch.dict(os.environ, {
            "LLM_PROVIDER": "gemini",
            "GEMINI_API_KEY": "",
            "LLM_FREE_ONLY": "true",
        }, clear=False):
            resp = p.call_provider(prompt="hi")
            self.assertEqual(resp.status, p.LLM_PROVIDER_KEY_MISSING)

    def test_free_only_true_allows_offline_mock(self):
        import llm_provider_client as p
        with mock.patch.dict(os.environ, {
            "LLM_PROVIDER": "offline_mock",
            "LLM_FREE_ONLY": "true",
        }, clear=False):
            resp = p.call_provider(prompt="hi")
            self.assertEqual(resp.status,
                              p.LLM_PROVIDER_OFFLINE_MOCK)


class TestFreeOnlyOptOut(unittest.TestCase):
    def test_free_only_false_allows_anthropic_key_missing(self):
        import llm_provider_client as p
        with mock.patch.dict(os.environ, {
            "LLM_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "",
            "LLM_FREE_ONLY": "false",
        }, clear=False):
            resp = p.call_provider(prompt="hi")
            # Free-only NOT blocking; missing key path instead.
            self.assertEqual(resp.status, p.LLM_PROVIDER_KEY_MISSING)

    def test_truthy_strings_keep_policy_on(self):
        # The four canonical truthy strings keep free-only ON.
        import llm_provider_client as p
        for truthy in ("true", "TRUE", "True", "1", "yes", "YES",
                         "on", "ON"):
            with mock.patch.dict(os.environ, {
                "LLM_PROVIDER": "anthropic",
                "ANTHROPIC_API_KEY": "x",
                "LLM_FREE_ONLY": truthy,
            }, clear=False):
                resp = p.call_provider(prompt="hi")
                self.assertEqual(
                    resp.status, p.LLM_PROVIDER_BLOCKED_BY_FREE_ONLY,
                    f"LLM_FREE_ONLY={truthy!r} should keep policy ON")


class TestEnumExposes(unittest.TestCase):
    def test_free_providers_set(self):
        import llm_provider_client as p
        self.assertIn("gemini", p.FREE_PROVIDERS)
        self.assertIn("offline_mock", p.FREE_PROVIDERS)
        self.assertIn("anthropic", p.PAID_PROVIDERS)
        self.assertIn("openai", p.PAID_PROVIDERS)
        self.assertIn("gemini", p.KNOWN_PROVIDERS)


class TestStatusTokenExposed(unittest.TestCase):
    def test_blocked_by_free_only_in_all_statuses(self):
        import llm_provider_client as p
        self.assertIn(p.LLM_PROVIDER_BLOCKED_BY_FREE_ONLY,
                       p.ALL_PROVIDER_STATUSES)
        self.assertIn(p.LLM_PROVIDER_MODEL_ERROR,
                       p.ALL_PROVIDER_STATUSES)


if __name__ == "__main__":
    unittest.main()
