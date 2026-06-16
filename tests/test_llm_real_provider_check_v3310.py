"""v3.31 (2026-06-16) — LLM real-provider activation check tests.

Hard safety:
- secret value NEVER appears in stdout/disk
- redact_secrets called on output
- AST proof: NO broker import
- operator instructions doc generated when missing
- standing markers footer
- default dry-run + smoke-test default false
"""

from __future__ import annotations

import ast
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "shared"))

import check_llm_real_provider_activation as mod  # noqa: E402


SECRET_VALUE = "AIZATHISSHOULDNEVERBEPRINTED12345ABCDEF"  # Alpaca-shape, NEVER printed


def _scrub_env() -> dict:
    """Return a copy of os.environ without GEMINI/ANTHROPIC/OPENAI keys."""
    out = dict(os.environ)
    for k in (
        "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        "LLM_PROVIDER", "LLM_FREE_ONLY",
    ):
        out.pop(k, None)
    return out


class _Tmp:
    def __init__(self):
        self.dir = tempfile.TemporaryDirectory()
    def path(self, name):
        return Path(self.dir.name) / name
    def cleanup(self):
        self.dir.cleanup()


class TestVerdictMissingKey(unittest.TestCase):
    def test_missing_key_returns_fallback_verdict_and_writes_instructions(self):
        with mock.patch.dict(os.environ, _scrub_env(), clear=True):
            payload = mod.build_payload(smoke_test=False, dry_run=True)
        self.assertEqual(
            payload["verdict"],
            mod.VERDICT_DETERMINISTIC_FALLBACK_UNTIL_SECRET_SET)
        self.assertFalse(payload["gemini_api_key_present"])
        self.assertEqual(payload["smoke_test_executed"], False)
        # Operator instructions present.
        self.assertEqual(len(payload["operator_instructions"]), 4)
        joined = " ".join(payload["operator_instructions"])
        self.assertIn("GEMINI_API_KEY", joined)
        self.assertIn("Settings -> Secrets and variables", joined)
        self.assertIn("aistudio.google.com/apikey", joined)


class TestVerdictKeyPresentNoSmoke(unittest.TestCase):
    def test_key_present_no_smoke_returns_detected_verdict(self):
        env = _scrub_env()
        env["GEMINI_API_KEY"] = SECRET_VALUE
        with mock.patch.dict(os.environ, env, clear=True):
            payload = mod.build_payload(smoke_test=False, dry_run=True)
        self.assertEqual(
            payload["verdict"],
            mod.VERDICT_PROVIDER_KEY_DETECTED_NO_SMOKE_TEST)
        self.assertTrue(payload["gemini_api_key_present"])
        self.assertFalse(payload["smoke_test_executed"])
        # operator_instructions empty (no missing/failed key)
        self.assertEqual(payload["operator_instructions"], [])


class TestVerdictKeyPresentSmokeOk(unittest.TestCase):
    def test_smoke_ok_returns_ready_verdict(self):
        env = _scrub_env()
        env["GEMINI_API_KEY"] = SECRET_VALUE
        # Mock the provider client call to return success.
        with mock.patch.dict(os.environ, env, clear=True):
            class _Resp:
                status = "LLM_PROVIDER_CALL_OK"
                text = "PROVIDER_SMOKE_OK"
            fake_p = mock.MagicMock()
            fake_p.LLM_PROVIDER_CALL_OK = "LLM_PROVIDER_CALL_OK"
            fake_p.call_provider = mock.MagicMock(return_value=_Resp())
            with mock.patch.dict(sys.modules, {"llm_provider_client": fake_p}):
                payload = mod.build_payload(
                    smoke_test=True, dry_run=False)
        self.assertEqual(payload["verdict"],
                          mod.VERDICT_REAL_PROVIDER_READY)
        self.assertTrue(payload["smoke_test_executed"])
        # Smoke text is redacted but the legitimate token survives.
        self.assertIn("PROVIDER_SMOKE_OK", payload["smoke_text_redacted"])


class TestSecretNeverInStdoutOrDisk(unittest.TestCase):
    def test_secret_value_never_in_stdout_or_persisted_files(self):
        env = _scrub_env()
        env["GEMINI_API_KEY"] = SECRET_VALUE
        tmp = _Tmp()
        out_json = tmp.path("out.json")
        out_doc  = tmp.path("out.md")
        buf = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True):
            with redirect_stdout(buf):
                rc = mod.main([
                    "--out-json", str(out_json),
                    "--out-doc",  str(out_doc),
                ])
        stdout = buf.getvalue()
        # Stdout MUST NOT contain the literal key.
        self.assertNotIn(SECRET_VALUE, stdout)
        # Persisted JSON MUST NOT contain the literal key.
        self.assertTrue(out_json.exists())
        json_text = out_json.read_text(encoding="utf-8")
        self.assertNotIn(SECRET_VALUE, json_text)
        # Persisted markdown MUST NOT contain the literal key.
        self.assertTrue(out_doc.exists())
        doc_text = out_doc.read_text(encoding="utf-8")
        self.assertNotIn(SECRET_VALUE, doc_text)
        tmp.cleanup()


class TestRedactSecretsCalled(unittest.TestCase):
    def test_smoke_text_is_routed_through_redact_secrets(self):
        env = _scrub_env()
        env["GEMINI_API_KEY"] = SECRET_VALUE

        # Build a provider response that literally echoes the secret —
        # the redactor must scrub it before persistence.
        class _Resp:
            status = "LLM_PROVIDER_CALL_OK"
            text = f"ok {SECRET_VALUE}"
        fake_p = mock.MagicMock()
        fake_p.LLM_PROVIDER_CALL_OK = "LLM_PROVIDER_CALL_OK"
        fake_p.call_provider = mock.MagicMock(return_value=_Resp())

        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.dict(sys.modules,
                                  {"llm_provider_client": fake_p}):
                payload = mod.build_payload(
                    smoke_test=True, dry_run=False)
        # The redacted smoke text must not contain the literal secret.
        self.assertNotIn(SECRET_VALUE, payload["smoke_text_redacted"])


class TestNoBrokerImportAst(unittest.TestCase):
    def test_module_does_not_import_alpaca_orders(self):
        src = (REPO_ROOT / "scripts"
                / "check_llm_real_provider_activation.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertNotIn("alpaca_orders", n.name)
            if isinstance(node, ast.ImportFrom):
                self.assertIsNotNone(node.module or "")
                self.assertNotEqual(node.module, "alpaca_orders")
                if node.module:
                    self.assertNotIn("alpaca_orders", node.module)


class TestStandingMarkers(unittest.TestCase):
    def test_standing_markers_present_in_payload_and_doc(self):
        with mock.patch.dict(os.environ, _scrub_env(), clear=True):
            payload = mod.build_payload(smoke_test=False, dry_run=True)
        for m in (
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
            "LLM_ADVISORY_ONLY",
        ):
            self.assertIn(m, payload["standing_markers"])
        doc = mod.render_doc(payload)
        for m in (
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
            "LLM_ADVISORY_ONLY",
        ):
            self.assertIn(m, doc)


class TestOperatorInstructionsDocGenerated(unittest.TestCase):
    def test_doc_contains_operator_instructions_when_key_missing(self):
        with mock.patch.dict(os.environ, _scrub_env(), clear=True):
            payload = mod.build_payload(smoke_test=False, dry_run=True)
            doc = mod.render_doc(payload)
        self.assertIn("Operator instructions", doc)
        self.assertIn("GEMINI_API_KEY", doc)


class TestDefaultDryRunIsTrue(unittest.TestCase):
    def test_main_default_dry_run_true(self):
        env = _scrub_env()
        with mock.patch.dict(os.environ, env, clear=True):
            tmp = _Tmp()
            out_json = tmp.path("o.json")
            out_doc  = tmp.path("o.md")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = mod.main([
                    "--out-json", str(out_json),
                    "--out-doc",  str(out_doc),
                ])
            self.assertEqual(rc, 0)
            raw = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertTrue(raw["dry_run"])
            self.assertFalse(raw["smoke_test_executed"])
            tmp.cleanup()


class TestSmokeTestDefaultFalse(unittest.TestCase):
    def test_argparse_default_smoke_test_false(self):
        env = _scrub_env()
        env["GEMINI_API_KEY"] = SECRET_VALUE
        with mock.patch.dict(os.environ, env, clear=True):
            tmp = _Tmp()
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = mod.main([
                    "--out-json", str(tmp.path("o.json")),
                    "--out-doc",  str(tmp.path("o.md")),
                ])
            self.assertEqual(rc, 0)
            raw = json.loads(tmp.path("o.json").read_text(encoding="utf-8"))
            # Smoke test not executed because operator did not pass
            # --smoke-test.
            self.assertFalse(raw["smoke_test_executed"])
            self.assertEqual(
                raw["verdict"],
                mod.VERDICT_PROVIDER_KEY_DETECTED_NO_SMOKE_TEST)
            tmp.cleanup()


class TestNoSecretLengthDisclosed(unittest.TestCase):
    def test_payload_does_not_contain_secret_length(self):
        env = _scrub_env()
        env["GEMINI_API_KEY"] = SECRET_VALUE
        with mock.patch.dict(os.environ, env, clear=True):
            payload = mod.build_payload(smoke_test=False, dry_run=True)
        # Payload must not include a "length" or "size" field for the
        # secret value.
        for k, v in payload.items():
            if isinstance(v, (int, float)):
                self.assertNotEqual(
                    v, len(SECRET_VALUE),
                    f"field {k} discloses secret length")


if __name__ == "__main__":
    unittest.main()
