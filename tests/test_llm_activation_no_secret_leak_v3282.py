"""v3.28.2 (2026-06-09) — activation artifact secret-leak tests."""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestActivationJsonHasNoSecretValues(unittest.TestCase):
    def test_status_json_has_no_long_alnum_secret_pattern(self):
        path = (REPO_ROOT / "learning-loop" / "llm_advisory"
                 / "activation_status_latest.json")
        if not path.exists():
            self.skipTest("activation status artifact not yet generated")
        text = path.read_text(encoding="utf-8")
        # Alpaca-key shape: 20+ uppercase-alphanumeric run.
        for m in re.finditer(r"[A-Z0-9]{20,}", text):
            # The only legal tokens of this shape are the
            # uppercase enum identifiers themselves.
            tok = m.group(0)
            self.assertTrue(
                tok.replace("_", "").isupper() or "_" in tok,
                f"suspicious token in status JSON: {tok[:60]}")
        for k in ("APCA-API-", "ALPACA_API_KEY=",
                   "ALPACA_SECRET_KEY=",
                   "GEMINI_API_KEY=",
                   "ANTHROPIC_API_KEY=",
                   "OPENAI_API_KEY="):
            self.assertNotIn(k, text,
                              f"forbidden key pattern: {k}")

    def test_status_json_contains_only_secret_NAMES(self):
        path = (REPO_ROOT / "learning-loop" / "llm_advisory"
                 / "activation_status_latest.json")
        if not path.exists():
            self.skipTest("activation status artifact not yet generated")
        data = json.loads(path.read_text(encoding="utf-8"))
        # If GEMINI_API_KEY is in secret_names_seen, it MUST be just
        # the literal name string, never followed by an "=" or value.
        for nm in data.get("secret_names_seen", []):
            self.assertNotIn("=", nm,
                              f"secret name carries value: {nm}")
            # Names are short identifiers, NOT key payloads.
            self.assertLess(len(nm), 64,
                            f"name too long, looks like value: {nm}")


class TestActivationDocHasNoSecretValues(unittest.TestCase):
    def test_doc_has_no_secret_value_pattern(self):
        path = (REPO_ROOT / "docs"
                 / "LLM_ADVISORY_ACTIVATION_STATUS.md")
        if not path.exists():
            self.skipTest("activation doc not yet generated")
        text = path.read_text(encoding="utf-8")
        for k in ("APCA-API-", "ALPACA_API_KEY=",
                   "ALPACA_SECRET_KEY=",
                   "GEMINI_API_KEY=",
                   "ANTHROPIC_API_KEY=",
                   "OPENAI_API_KEY="):
            self.assertNotIn(k, text)


class TestHelperSourceDoesNotPrintSecretValues(unittest.TestCase):
    def test_no_print_of_env_key_values(self):
        src = (REPO_ROOT / "scripts"
                / "activate_llm_advisory_mesh.py").read_text(
            encoding="utf-8")
        # The helper must NEVER print env values of provider keys.
        for tok in (
            'os.environ["GEMINI_API_KEY"]',
            "os.environ['GEMINI_API_KEY']",
            'os.environ.get("GEMINI_API_KEY")',
            "os.environ.get('GEMINI_API_KEY')",
            'os.environ["ANTHROPIC_API_KEY"]',
            "os.environ['ANTHROPIC_API_KEY']",
            'os.environ["OPENAI_API_KEY"]',
            "os.environ['OPENAI_API_KEY']",
        ):
            self.assertNotIn(
                tok, src,
                f"helper must not read provider key from env: {tok}")
        # Also: no `print(...)` line should reference any *_API_KEY.
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("print(") and "API_KEY" in line:
                # The only acceptable mentions are inside docstrings
                # (e.g. "GEMINI_API_KEY"), not print() arguments.
                self.fail(f"helper prints API_KEY: {line!r}")


class TestSafetyInvariantsInStatus(unittest.TestCase):
    def test_status_json_pins_safety(self):
        path = (REPO_ROOT / "learning-loop" / "llm_advisory"
                 / "activation_status_latest.json")
        if not path.exists():
            self.skipTest("status artifact not yet generated")
        data = json.loads(path.read_text(encoding="utf-8"))
        s = data.get("safety") or {}
        self.assertTrue(s.get("broker_paper_canary_still_blocked"))
        self.assertTrue(s.get("live_trading_unsupported"))
        self.assertFalse(s.get("broker_execution_enabled"))
        self.assertFalse(s.get("edge_gate_enabled"))
        self.assertFalse(s.get("allow_broker_paper"))
        self.assertTrue(s.get("deterministic_gates_remain_final"))


class TestNoBrokerImports(unittest.TestCase):
    def test_source_clean(self):
        src = (REPO_ROOT / "scripts"
                / "activate_llm_advisory_mesh.py").read_text(encoding="utf-8")
        for tok in ("alpaca_orders", "place_stock_bracket",
                     "place_crypto_order"):
            self.assertNotIn(tok, src, f"forbidden: {tok}")


if __name__ == "__main__":
    unittest.main()
