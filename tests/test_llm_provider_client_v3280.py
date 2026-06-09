"""v3.28 (2026-06-09) — provider client tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestOfflineMockNeverHitsNetwork(unittest.TestCase):
    def test_default_offline_mock(self):
        import llm_provider_client as p
        # Patch requests.post — must NOT be called.
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "offline_mock"},
                                clear=False):
            import requests
            with mock.patch.object(requests, "post") as post:
                resp = p.call_provider(prompt="hi")
                self.assertEqual(resp.status, p.LLM_PROVIDER_OFFLINE_MOCK)
                self.assertFalse(post.called,
                                   "offline_mock must NOT call network")

    def test_offline_mock_response_advisory_only(self):
        import llm_provider_client as p
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "offline_mock"},
                                clear=False):
            resp = p.call_provider(prompt="hi")
            self.assertIn("advisory_only", resp.text)


class TestProviderKeyMissing(unittest.TestCase):
    def test_anthropic_missing_key_returns_status(self):
        # v3.28.2 — paid providers are now blocked under default
        # LLM_FREE_ONLY=true. Operator must explicitly opt out to
        # reach the legacy KEY_MISSING path.
        import llm_provider_client as p
        with mock.patch.dict(os.environ, {
            "LLM_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "",
            "LLM_FREE_ONLY": "false",
        }, clear=False):
            resp = p.call_provider(prompt="hi")
            self.assertEqual(resp.status, p.LLM_PROVIDER_KEY_MISSING)
            self.assertIn("ANTHROPIC_API_KEY", resp.text)

    def test_openai_missing_key_returns_status(self):
        # v3.28.2 — paid provider opt-in required.
        import llm_provider_client as p
        with mock.patch.dict(os.environ, {
            "LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "",
            "LLM_FREE_ONLY": "false",
        }, clear=False):
            resp = p.call_provider(prompt="hi")
            self.assertEqual(resp.status, p.LLM_PROVIDER_KEY_MISSING)


class TestProviderFailSoft(unittest.TestCase):
    def test_network_exception_returns_failed_status(self):
        # v3.28.2 — paid provider opt-in required.
        import llm_provider_client as p
        with mock.patch.dict(os.environ, {
            "LLM_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "x" * 24,
            "LLM_FREE_ONLY": "false",
        }, clear=False):
            import requests
            with mock.patch.object(
                requests, "post",
                side_effect=RuntimeError("offline"),
            ):
                resp = p.call_provider(prompt="hi")
                self.assertEqual(resp.status,
                                  p.LLM_PROVIDER_CALL_FAILED)


class TestNoSecretLeak(unittest.TestCase):
    def test_response_text_redacts_long_uppercase_tokens(self):
        import llm_provider_client as p
        # _redact is invoked on any provider-call error message.
        text = "context AKAAAAAAAAAAAAAAAAAA bar"
        self.assertNotIn("AKAAAAAAAAAAAAAAAAAA", p._redact(text))
        self.assertIn("REDACTED", p._redact(text))

    def test_response_redacts_anthropic_key_shape(self):
        import llm_provider_client as p
        text = "leaked sk-ant-abcdefABCDEF1234 here"
        self.assertNotIn("sk-ant-abcdefABCDEF1234", p._redact(text))


class TestNoBrokerImports(unittest.TestCase):
    def test_source_clean(self):
        src = (REPO_ROOT / "shared"
                / "llm_provider_client.py").read_text(encoding="utf-8")
        for tok in (
            "alpaca_orders", "safe_close",
            "place_stock_bracket", "place_crypto_order",
            "execute_stock_signal", "execute_crypto_signal",
        ):
            self.assertNotIn(tok, src, f"forbidden: {tok}")


if __name__ == "__main__":
    unittest.main()
