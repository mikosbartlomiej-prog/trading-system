"""v3.29 ETAP 7 (2026-06-16) — Daily Operational Brief tests.

Asserts the contract of
``scripts/generate_daily_operational_brief_v329etap7.py``:

- Numeric claims cite source path.
- Unsupported claims flagged ``CLAIM_UNSUPPORTED`` or omitted.
- Top blockers appear in top section.
- LLM advisory cannot hide blockers (blockers are pulled from
  deterministic artefacts, not from advisory output).
- No order placement (AST gate).
- Standing markers present.
- TRADING_EXECUTION_ON always false in brief output.
- File written to briefs/<date>.md.
- AST: no alpaca_orders import.
- Brief refuses to claim 92 / 18 / 80-day unless backed by evidence.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Load module dynamically (the script is not a normal importable
# package member).
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_daily_operational_brief_v329etap7.py"
SCRIPT_SRC  = SCRIPT_PATH.read_text(encoding="utf-8")


def _import_brief_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "brief_v329etap7", str(SCRIPT_PATH))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore
    return mod


# ─── 1. Numeric claims cite source path ────────────────────────────────────

class TestNumericClaimsCiteSource(unittest.TestCase):
    def test_cite_helper_includes_source_tag(self):
        mod = _import_brief_module()
        out = mod._cite(123, "x/y.json::z")
        self.assertIn("123", out)
        self.assertIn("source", out)
        self.assertIn("x/y.json::z", out)


# ─── 2. Unsupported claims flagged CLAIM_UNSUPPORTED ───────────────────────

class TestUnsupportedClaimsFlagged(unittest.TestCase):
    def test_none_value_renders_claim_unsupported(self):
        mod = _import_brief_module()
        out = mod._cite(None, "missing/file.json")
        self.assertIn("CLAIM_UNSUPPORTED", out)
        self.assertIn("missing", out)


# ─── 3. Top blockers in top section ────────────────────────────────────────

class TestTopBlockersInTopSection(unittest.TestCase):
    def test_blocker_section_appears_above_other_sections(self):
        mod = _import_brief_module()
        tmpdir = tempfile.TemporaryDirectory()
        try:
            os.chdir(tmpdir.name)
            # No artefacts — brief still renders.
            with mock.patch.object(mod, "REPO_ROOT",
                                       Path(tmpdir.name)):
                text = mod.render_brief(as_of="2026-06-16")
            # Top blockers section comes before equity reconciliation.
            top_idx = text.find("## Top blockers")
            equity_idx = text.find("## Equity reconciliation")
            self.assertGreaterEqual(top_idx, 0)
            self.assertGreaterEqual(equity_idx, 0)
            self.assertLess(top_idx, equity_idx)
        finally:
            tmpdir.cleanup()


# ─── 4. LLM advisory cannot hide blockers ──────────────────────────────────

class TestLLMAdvisoryCannotHideBlockers(unittest.TestCase):
    def test_blocker_list_pulled_from_deterministic_artefacts(self):
        mod = _import_brief_module()
        art = {
            "system_activation_latest": {"decision": "BLOCK_X"},
            "allocator_gate_latest":   {"decision": "BLOCK_Y"},
        }
        blockers = mod._top_blockers(art)
        # Decisions come from deterministic artefacts, not from any
        # LLM advisory file.
        self.assertTrue(any("BLOCK_X" in b for b in blockers))
        self.assertTrue(any("BLOCK_Y" in b for b in blockers))


# ─── 5. No order placement ─────────────────────────────────────────────────

class TestNoOrderPlacement(unittest.TestCase):
    def test_no_broker_function_call_in_script(self):
        forbidden_names = {
            "submit_order", "place_order", "safe_close",
            "cancel_order", "close_position", "place_stock_order",
            "place_crypto_order", "place_option_order",
        }
        tree = ast.parse(SCRIPT_SRC)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fname = ""
                if isinstance(node.func, ast.Name):
                    fname = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    fname = node.func.attr
                self.assertNotIn(fname, forbidden_names)


# ─── 6. Standing markers present ───────────────────────────────────────────

class TestStandingMarkersPresent(unittest.TestCase):
    def test_brief_contains_standing_markers_section(self):
        mod = _import_brief_module()
        tmpdir = tempfile.TemporaryDirectory()
        try:
            with mock.patch.object(mod, "REPO_ROOT",
                                       Path(tmpdir.name)):
                text = mod.render_brief(as_of="2026-06-16")
            self.assertIn("## Standing markers", text)
            self.assertIn("LIVE_TRADING_UNSUPPORTED", text)
            self.assertIn("NO_ORDER_PLACEMENT", text)
        finally:
            tmpdir.cleanup()


# ─── 7. TRADING_EXECUTION_ON always false ──────────────────────────────────

class TestTradingExecutionAlwaysFalse(unittest.TestCase):
    def test_render_lines_include_trading_execution_false(self):
        mod = _import_brief_module()
        tmpdir = tempfile.TemporaryDirectory()
        # Make sure no env truthy slips in.
        os.environ.pop("TRADING_EXECUTION_ON", None)
        try:
            with mock.patch.object(mod, "REPO_ROOT",
                                       Path(tmpdir.name)):
                text = mod.render_brief(as_of="2026-06-16")
            self.assertIn("TRADING_EXECUTION_ON=false", text)
        finally:
            tmpdir.cleanup()


# ─── 8. File written to briefs/<date>.md ───────────────────────────────────

class TestFileWrittenToBriefsDir(unittest.TestCase):
    def test_main_writes_brief_file(self):
        mod = _import_brief_module()
        tmpdir = tempfile.TemporaryDirectory()
        try:
            with mock.patch.object(mod, "REPO_ROOT",
                                       Path(tmpdir.name)):
                rc = mod.main([
                    "--as-of", "2026-06-16",
                    "--no-write-sidecar",
                    "--no-write-doc",
                ])
            self.assertEqual(rc, 0)
            self.assertTrue(
                (Path(tmpdir.name)
                 / "briefs" / "2026-06-16.md").exists())
        finally:
            tmpdir.cleanup()


# ─── 9. AST: no alpaca_orders import ───────────────────────────────────────

class TestNoAlpacaOrdersImport(unittest.TestCase):
    def test_no_alpaca_orders_import_in_script(self):
        tree = ast.parse(SCRIPT_SRC)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("alpaca_orders", alias.name)
            elif isinstance(node, ast.ImportFrom):
                self.assertFalse(
                    node.module and "alpaca_orders" in node.module)


# ─── 10. Brief refuses to claim 92 / 18 / 80-day without evidence ──────────

class TestBriefRefusesUnverifiedClaims(unittest.TestCase):
    def test_no_92_readiness_claim_without_evidence(self):
        mod = _import_brief_module()
        tmpdir = tempfile.TemporaryDirectory()
        try:
            with mock.patch.object(mod, "REPO_ROOT",
                                       Path(tmpdir.name)):
                text = mod.render_brief(as_of="2026-06-16")
            # No "92" appears as a readiness claim outside of any
            # legitimate citation.
            self.assertNotIn("92%", text)
            self.assertNotIn("18 LLM agents", text)
            self.assertNotIn("80-day", text)
            self.assertNotIn("80 days of LLM failure", text)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
