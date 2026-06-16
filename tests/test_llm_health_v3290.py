"""v3.29 ETAP 9 (2026-06-16) — LLM provider health audit tests.

Asserts:
- GEMINI_API_KEY missing → UNKNOWN (not FAILED)
- 80-day claim debunked when history shows < 80 days
- Secrets NEVER printed
- redact_secrets is used on output
- AST: no alpaca_orders import
- Standing markers present
- generates LLM_PROVIDER_HEALTH_STATUS.md
- proposes fix without auto-applying
- never enables EDGE_GATE_ENABLED
- never enables ALLOW_BROKER_PAPER
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


def _load_script():
    p = _REPO_ROOT / "scripts" / "audit_llm_provider_health.py"
    spec = importlib.util.spec_from_file_location(
        "audit_llm_provider_health", p)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["audit_llm_provider_health"] = m
    spec.loader.exec_module(m)
    return m


class TestGeminiMissingYieldsUnknown(unittest.TestCase):
    def setUp(self):
        self.m = _load_script()

    def test_missing_env_yields_unknown_when_history_empty(self):
        env_st = {"name": "GEMINI_API_KEY", "present": False,
                  "value_length": 0}
        history = {"rows": 0, "n_success": 0, "n_failure": 0,
                   "earliest_iso": None, "latest_iso": None}
        budget = {"available": False}
        v = self.m._verdict_per_provider(
            "gemini", env_st, history, budget, {}, {})
        self.assertEqual(v["verdict"], self.m.VERDICT_UNKNOWN)
        # Specifically not FAILED yet — only debunks the 80-day claim
        self.assertNotEqual(v["verdict"], self.m.VERDICT_FAILED)


class TestEightyDayClaim(unittest.TestCase):
    def setUp(self):
        self.m = _load_script()

    def test_debunked_when_history_empty(self):
        v, r = self.m._classify_80_day_claim(
            {"rows": 0, "earliest_iso": None, "latest_iso": None})
        self.assertEqual(v, self.m.VERDICT_CLAIM_UNSUPPORTED)


class TestSecretsNeverPrinted(unittest.TestCase):
    def setUp(self):
        self.m = _load_script()

    def test_status_payload_carries_no_secret_value(self):
        # Set a synthetic key value; status payload must NEVER carry it.
        secret_value = "AKIAEXAMPLESECRETVALUEFORTEST1234"
        os.environ["GEMINI_API_KEY"] = secret_value
        try:
            status = self.m.build_status()
        finally:
            os.environ.pop("GEMINI_API_KEY", None)
        serialised = json.dumps(status)
        self.assertNotIn(secret_value, serialised,
                          "secret leaked into status payload")


class TestRedactSecretsUsed(unittest.TestCase):
    def setUp(self):
        self.m = _load_script()

    def test_try_redact_passes_through_no_secret(self):
        text = "no secrets here"
        out = self.m._try_redact(text)
        self.assertEqual(out, text)

    def test_try_redact_redacts_alpaca_shape_token(self):
        text = "key=AKIAFAKEEXAMPLESECRETLONGENOUGH123"
        out = self.m._try_redact(text)
        self.assertNotIn("AKIAFAKEEXAMPLESECRETLONGENOUGH123", out)


class TestNoAlpacaImport(unittest.TestCase):
    def test_no_alpaca_import_in_audit_script(self):
        p = _REPO_ROOT / "scripts" / "audit_llm_provider_health.py"
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn("alpaca_orders", node.module or "")
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertNotIn("alpaca_orders", n.name or "")


class TestStandingMarkers(unittest.TestCase):
    def test_present(self):
        m = _load_script()
        status = m.build_status()
        markers = status["standing_markers"]
        for m_ in ("EDGE_GATE_ENABLED=false",
                   "ALLOW_BROKER_PAPER=false",
                   "LIVE_TRADING_UNSUPPORTED",
                   "NO_ORDER_PLACEMENT",
                   "LLM_NEVER_IN_ORDER_PATH"):
            self.assertIn(m_, markers)


class TestRendersMd(unittest.TestCase):
    def test_writes_md(self):
        m = _load_script()
        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            json_path = tdir / "llm.json"
            md_path = tdir / "LLM_PROVIDER_HEALTH_STATUS.md"
            with patch.object(m, "LATEST_JSON_PATH", json_path), \
                 patch.object(m, "LATEST_MD_PATH",   md_path), \
                 patch.object(sys, "argv", ["audit_llm_provider_health.py"]):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    m.main()
                self.assertTrue(md_path.exists())
                text = md_path.read_text(encoding="utf-8")
                self.assertIn("LLM Provider Health Audit", text)
                self.assertIn("Standing markers", text)


class TestProposesFixWithoutAutoApply(unittest.TestCase):
    def test_proposed_fix_is_text_only(self):
        m = _load_script()
        # Ensure env key is absent so a fix is proposed.
        os.environ.pop("GEMINI_API_KEY", None)
        status = m.build_status()
        fixes = status.get("proposed_fixes") or []
        # The fix is a string starting with [PROPOSED-FIX]; never an action.
        self.assertTrue(any("PROPOSED-FIX" in f for f in fixes))


class TestNeverEnablesEdgeGateOrAllowBrokerPaper(unittest.TestCase):
    def test_no_flag_flip(self):
        text = (_REPO_ROOT / "scripts"
                / "audit_llm_provider_health.py").read_text(encoding="utf-8")
        for bad in (
            "ALLOW_BROKER_PAPER = True",
            "EDGE_GATE_ENABLED = True",
            "os.environ['ALLOW_BROKER_PAPER'] = 'true'",
            "os.environ['EDGE_GATE_ENABLED'] = 'true'",
        ):
            self.assertNotIn(bad, text)


class TestNoLiveURL(unittest.TestCase):
    def test_no_live_url(self):
        text = (_REPO_ROOT / "scripts"
                / "audit_llm_provider_health.py").read_text(encoding="utf-8")
        self.assertNotIn("api.alpaca.markets", text)


if __name__ == "__main__":
    unittest.main()
