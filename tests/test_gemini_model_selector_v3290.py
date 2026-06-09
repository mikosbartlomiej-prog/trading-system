"""v3.29 (2026-06-09) — Gemini model selector tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestNoKey(unittest.TestCase):
    def test_no_key_returns_no_key_status(self):
        import gemini_model_selector as sel
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""},
                                clear=False):
            r = sel.discover_models()
        self.assertEqual(r.status, sel.GEMINI_MODEL_DISCOVERY_NO_KEY)


class TestClassifyHttpStatus(unittest.TestCase):
    def setUp(self):
        import gemini_model_selector as sel
        self.sel = sel

    def test_400_to_model_unavailable(self):
        self.assertEqual(
            self.sel.classify_http_status(400),
            self.sel.GEMINI_MODEL_UNAVAILABLE)

    def test_404_to_model_unavailable(self):
        self.assertEqual(
            self.sel.classify_http_status(404),
            self.sel.GEMINI_MODEL_UNAVAILABLE)

    def test_401_to_auth(self):
        self.assertEqual(
            self.sel.classify_http_status(401),
            self.sel.GEMINI_AUTH_FAILED)

    def test_403_to_permission(self):
        self.assertEqual(
            self.sel.classify_http_status(403),
            self.sel.GEMINI_PERMISSION_DENIED)

    def test_429_to_quota(self):
        self.assertEqual(
            self.sel.classify_http_status(429),
            self.sel.GEMINI_QUOTA_OR_RATE_LIMIT)

    def test_500_to_endpoint(self):
        self.assertEqual(
            self.sel.classify_http_status(503),
            self.sel.GEMINI_ENDPOINT_ERROR)


class TestSelectionMockDiscovery(unittest.TestCase):
    def test_configured_model_returned_when_present(self):
        import gemini_model_selector as sel

        class _R:
            status_code = 200
            def json(self):
                return {"models": [
                    {"name": "models/gemini-flash-latest",
                     "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-2.5-flash",
                     "supportedGenerationMethods": ["generateContent"]},
                ]}

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "x"},
                                clear=False):
            import requests
            with mock.patch.object(requests, "get", return_value=_R()):
                r = sel.select_model(
                    configured_model="gemini-2.5-flash")
        self.assertEqual(r.status, sel.GEMINI_MODEL_SELECTED)
        self.assertEqual(r.selected_model, "gemini-2.5-flash")

    def test_candidate_fallback_when_configured_missing(self):
        import gemini_model_selector as sel

        class _R:
            status_code = 200
            def json(self):
                return {"models": [
                    {"name": "models/gemini-flash-latest",
                     "supportedGenerationMethods": ["generateContent"]},
                ]}

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "x"},
                                clear=False):
            import requests
            with mock.patch.object(requests, "get", return_value=_R()):
                r = sel.select_model(
                    configured_model="not-a-real-model")
        self.assertEqual(r.status, sel.GEMINI_MODEL_SELECTED)
        self.assertEqual(r.selected_model, "gemini-flash-latest")

    def test_excludes_non_text_models(self):
        import gemini_model_selector as sel

        class _R:
            status_code = 200
            def json(self):
                return {"models": [
                    {"name": "models/text-embedding-005",
                     "supportedGenerationMethods": ["embedContent"]},
                    {"name": "models/imagen-3.0",
                     "supportedGenerationMethods": ["generateImage"]},
                    {"name": "models/gemini-2.5-flash",
                     "supportedGenerationMethods": ["generateContent"]},
                ]}

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "x"},
                                clear=False):
            import requests
            with mock.patch.object(requests, "get", return_value=_R()):
                r = sel.discover_models()
        self.assertNotIn("text-embedding-005", r.discovered)
        self.assertNotIn("imagen-3.0", r.discovered)
        self.assertIn("gemini-2.5-flash", r.discovered)


class TestDiscoveryFailedDoesNotRaise(unittest.TestCase):
    def test_http_500_returns_endpoint_status(self):
        import gemini_model_selector as sel

        class _R:
            status_code = 500
            def json(self):
                return {}

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "x"},
                                clear=False):
            import requests
            with mock.patch.object(requests, "get", return_value=_R()):
                r = sel.discover_models()
        self.assertEqual(
            r.status, sel.GEMINI_MODEL_DISCOVERY_ENDPOINT)
        self.assertEqual(
            r.failure_category, sel.GEMINI_ENDPOINT_ERROR)


class TestRedactor(unittest.TestCase):
    def test_redacts_aiza_key(self):
        import gemini_model_selector as sel
        out = sel._redact_for_log(
            "leak AIzaSyABCDEF1234567890123456789012 here")
        self.assertNotIn("AIzaSyABCDEF1234567890123456789012", out)
        self.assertIn("REDACTED", out)


class TestNoBrokerImports(unittest.TestCase):
    def test_source_clean(self):
        src = (REPO_ROOT / "shared"
                / "gemini_model_selector.py").read_text(encoding="utf-8")
        for tok in ("alpaca_orders", "place_stock_bracket",
                     "place_crypto_order", "submit_order",
                     "place_order"):
            self.assertNotIn(tok, src)


if __name__ == "__main__":
    unittest.main()
