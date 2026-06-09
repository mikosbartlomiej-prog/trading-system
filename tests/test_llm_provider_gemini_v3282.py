"""v3.28.2 (2026-06-09) — Gemini provider tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class _Iso(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {
            "LLM_PROVIDER": "gemini",
            "LLM_FREE_ONLY": "true",
            "GEMINI_API_KEY": "",
            "GEMINI_MODEL":   "gemini-2.5-flash-lite",
            "ANTHROPIC_API_KEY": "",
            "OPENAI_API_KEY":    "",
        }, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()


class TestGeminiMissingKeyFailsSoft(_Iso):
    def test_returns_key_missing(self):
        import llm_provider_client as p
        resp = p.call_provider(prompt="hi")
        self.assertEqual(resp.status, p.LLM_PROVIDER_KEY_MISSING)
        # Key env name appears in status text; raw key value never does.
        self.assertIn("GEMINI_API_KEY", resp.text)


class TestGeminiSuccessParsed(_Iso):
    def test_happy_path_parses_candidates_content_parts_text(self):
        import llm_provider_client as p

        class _R:
            status_code = 200
            def json(self):
                return {
                    "candidates": [
                        {"content": {"parts": [
                            {"text": "advisory hello"}
                        ]}}
                    ]
                }

        with mock.patch.dict(os.environ, {
            "GEMINI_API_KEY": "fake-key-value-12345",
        }, clear=False):
            import requests
            with mock.patch.object(requests, "post",
                                       return_value=_R()) as post:
                resp = p.call_provider(prompt="hello")
        self.assertEqual(resp.status, p.LLM_PROVIDER_CALL_OK)
        self.assertEqual(resp.provider, "gemini")
        self.assertEqual(resp.text, "advisory hello")
        # Caller's URL must NOT contain the api key in plain logged
        # form (the URL uses the key as a query param; this is a
        # Google requirement, but the value itself never appears in
        # resp.text).
        self.assertNotIn("fake-key-value-12345", resp.text)


class TestGeminiHttpFailureFailsSoft(_Iso):
    def test_500_routes_to_call_failed(self):
        import llm_provider_client as p

        class _R:
            status_code = 500
            def json(self):
                return {}

        with mock.patch.dict(os.environ, {
            "GEMINI_API_KEY": "x",
        }, clear=False):
            import requests
            with mock.patch.object(requests, "post",
                                       return_value=_R()):
                resp = p.call_provider(prompt="hi")
        self.assertEqual(resp.status, p.LLM_PROVIDER_CALL_FAILED)


class TestGeminiModelErrorDistinct(_Iso):
    def test_400_routes_to_model_error(self):
        import llm_provider_client as p

        class _R:
            status_code = 400
            def json(self):
                return {}

        with mock.patch.dict(os.environ, {
            "GEMINI_API_KEY": "x",
            "GEMINI_MODEL":   "nonexistent-model-v0",
        }, clear=False):
            import requests
            with mock.patch.object(requests, "post",
                                       return_value=_R()):
                resp = p.call_provider(prompt="hi")
        self.assertEqual(resp.status, p.LLM_PROVIDER_MODEL_ERROR)

    def test_404_routes_to_model_error(self):
        import llm_provider_client as p

        class _R:
            status_code = 404
            def json(self):
                return {}

        with mock.patch.dict(os.environ, {
            "GEMINI_API_KEY": "x",
        }, clear=False):
            import requests
            with mock.patch.object(requests, "post",
                                       return_value=_R()):
                resp = p.call_provider(prompt="hi")
        self.assertEqual(resp.status, p.LLM_PROVIDER_MODEL_ERROR)


class TestGeminiNetworkExceptionFailsSoft(_Iso):
    def test_exception_routes_to_call_failed(self):
        import llm_provider_client as p
        with mock.patch.dict(os.environ, {
            "GEMINI_API_KEY": "x",
        }, clear=False):
            import requests
            with mock.patch.object(
                requests, "post",
                side_effect=RuntimeError("offline"),
            ):
                resp = p.call_provider(prompt="hi")
        self.assertEqual(resp.status, p.LLM_PROVIDER_CALL_FAILED)


class TestGeminiResponseTextRedactsSecrets(_Iso):
    def test_redacts_uppercase_alnum_run(self):
        import llm_provider_client as p

        class _R:
            status_code = 200
            def json(self):
                # Pretend Gemini echoed back something that looked
                # like an API key (it never should — but the
                # redactor protects us).
                return {"candidates": [{"content": {"parts": [
                    {"text": "leak AKAAAAAAAAAAAAAAAAAA tail"}
                ]}}]}

        with mock.patch.dict(os.environ, {
            "GEMINI_API_KEY": "x",
        }, clear=False):
            import requests
            with mock.patch.object(requests, "post",
                                       return_value=_R()):
                resp = p.call_provider(prompt="hi")
        self.assertNotIn("AKAAAAAAAAAAAAAAAAAA", resp.text)
        self.assertIn("REDACTED", resp.text)


class TestGeminiNeverImportsBrokerOrders(unittest.TestCase):
    def test_source_clean(self):
        src = (REPO_ROOT / "shared"
                / "llm_provider_client.py").read_text(encoding="utf-8")
        for tok in (
            "alpaca_orders", "place_stock_bracket",
            "place_crypto_order", "execute_stock_signal",
            "execute_crypto_signal",
        ):
            self.assertNotIn(tok, src, f"forbidden: {tok}")


if __name__ == "__main__":
    unittest.main()
