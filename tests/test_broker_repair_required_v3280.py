"""v3.28 ETAP 4 (2026-06-16) — tests for shared/broker_repair_required.py.

Asserts the hard invariants laid out in the module docstring.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))

import broker_repair_required as brr  # noqa: E402


class _IsolatedStateMixin:
    """Mixin that points the module at a tmp state file + tmp audit dir."""

    def setUp(self):  # type: ignore[override]
        self._tmp = tempfile.TemporaryDirectory()
        self._state_path = os.path.join(self._tmp.name, "brr_latest.json")
        self._audit_dir = os.path.join(self._tmp.name, "audit")
        self._prev_state_env = os.environ.pop("BROKER_REPAIR_REQUIRED_PATH", None)
        self._prev_audit_env = os.environ.pop("AUDIT_TRADING_DIR", None)
        os.environ["BROKER_REPAIR_REQUIRED_PATH"] = self._state_path
        os.environ["AUDIT_TRADING_DIR"] = self._audit_dir

    def tearDown(self):  # type: ignore[override]
        os.environ.pop("BROKER_REPAIR_REQUIRED_PATH", None)
        os.environ.pop("AUDIT_TRADING_DIR", None)
        if self._prev_state_env is not None:
            os.environ["BROKER_REPAIR_REQUIRED_PATH"] = self._prev_state_env
        if self._prev_audit_env is not None:
            os.environ["AUDIT_TRADING_DIR"] = self._prev_audit_env
        self._tmp.cleanup()


class TestBrokerRepairRequired(_IsolatedStateMixin, unittest.TestCase):
    def test_01_mark_creates_entry(self):
        # v3.30 (2026-06-16): symbol is canonicalized — AVAXUSD → AVAX/USD.
        entry = brr.mark_repair_required(
            "AVAXUSD",
            incident_type="P13_BRACKET_INTERLOCK",
            error="Alpaca 403 insufficient balance",
        )
        self.assertEqual(entry.symbol, "AVAX/USD")
        self.assertEqual(entry.failed_attempts, 1)
        self.assertTrue(os.path.exists(self._state_path))

    def test_02_repeated_mark_increments(self):
        brr.mark_repair_required("AVAXUSD", incident_type="P13", error="e1")
        brr.mark_repair_required("AVAXUSD", incident_type="P13", error="e2")
        e3 = brr.mark_repair_required("AVAXUSD", incident_type="P13", error="e3")
        self.assertEqual(e3.failed_attempts, 3)
        self.assertEqual(e3.last_error, "e3")

    def test_03_is_repair_required_after_mark(self):
        self.assertFalse(brr.is_repair_required("AVAXUSD"))
        brr.mark_repair_required("AVAXUSD", incident_type="P13", error="e")
        self.assertTrue(brr.is_repair_required("AVAXUSD"))

    def test_04_clear_refuses_without_marker(self):
        brr.mark_repair_required("AVAXUSD", incident_type="P13", error="e")
        # Marker path that does not exist on disk → must refuse.
        ok = brr.clear_repair("AVAXUSD", "/nonexistent/path/marker.txt")
        self.assertFalse(ok)
        self.assertTrue(brr.is_repair_required("AVAXUSD"),
                        "clear_repair must NOT clear when marker absent")

    def test_05_clear_accepts_with_marker(self):
        brr.mark_repair_required("AVAXUSD", incident_type="P13", error="e")
        marker = os.path.join(self._tmp.name, "operator_marker.txt")
        with open(marker, "w") as f:
            f.write("operator confirmed")
        ok = brr.clear_repair("AVAXUSD", marker)
        self.assertTrue(ok)
        self.assertFalse(brr.is_repair_required("AVAXUSD"))

    def test_06_ast_no_alpaca_import(self):
        path = _REPO_ROOT / "shared" / "broker_repair_required.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden = {"alpaca_orders", "shared.alpaca_orders"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertNotIn(n.name, forbidden,
                                     f"Forbidden import {n.name}")
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, forbidden,
                                 f"Forbidden from-import {node.module}")

    def test_07_ast_no_submit_or_safe_close(self):
        path = _REPO_ROOT / "shared" / "broker_repair_required.py"
        src = path.read_text(encoding="utf-8")
        # Strip comments + docstrings to avoid hitting the explanatory
        # text in the module header.
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Call,)):
                func = node.func
                name = ""
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                self.assertNotIn(name, {"submit_order", "place_order", "safe_close",
                                        "cancel_order", "close_position"},
                                 f"Forbidden call {name}")

    def test_08_save_atomic(self):
        # Calling save_state twice in a row must not leave .tmp residue.
        brr.save_state({})
        brr.save_state({})
        tmp = self._state_path + ".tmp"
        self.assertFalse(os.path.exists(tmp), "atomic write must not leave .tmp file")
        # File must be valid JSON.
        with open(self._state_path) as f:
            json.load(f)

    def test_09_p13_retry_budget_is_three(self):
        self.assertEqual(brr.P13_RETRY_BUDGET, 3)

    def test_10_dedupe_window_is_600(self):
        self.assertEqual(brr.SAFE_MODE_DEDUPE_WINDOW_SECONDS, 600)

    def test_11_load_returns_empty_when_missing(self):
        # Fresh tmp dir, state never written → empty dict.
        self.assertEqual(brr.load_state(), {})

    def test_12_get_blocked_symbols_returns_set(self):
        self.assertEqual(brr.get_blocked_symbols(), set())
        # v3.30 (2026-06-16): AVAXUSD and ETHUSD canonicalize to
        # AVAX/USD and ETH/USD respectively.
        brr.mark_repair_required("AVAXUSD", incident_type="P13", error="e")
        brr.mark_repair_required("ETHUSD", incident_type="P13", error="e")
        s = brr.get_blocked_symbols()
        self.assertIsInstance(s, set)
        self.assertEqual(s, {"AVAX/USD", "ETH/USD"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
