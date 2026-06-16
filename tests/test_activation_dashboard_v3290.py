"""v3.29 ETAP 10 (2026-06-16) — tests for scripts/build_system_activation_status.py.

Asserts:

* dashboard contains all 20 subsystems,
* ``WHOLE_SOLUTION_SAFE_ON`` is True,
* ``TRADING_EXECUTION_ON`` is always False (write-time literal),
* ``LLM_EXECUTION_AUTHORITY`` is always False (write-time literal),
* ``OPERATOR_ACTION_REQUIRED`` is True when blockers exist,
* standing markers present in both JSON and Markdown,
* no broker call (AST guard),
* AST has no ``alpaca_orders`` import.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


def _load_dashboard_module():
    script_path = _REPO_ROOT / "scripts" / "build_system_activation_status.py"
    if "build_system_activation_status" in sys.modules:
        del sys.modules["build_system_activation_status"]
    spec = importlib.util.spec_from_file_location(
        "build_system_activation_status", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["build_system_activation_status"] = module
    spec.loader.exec_module(module)
    return module


class _IsolatedEnv(unittest.TestCase):
    """Re-route the dashboard outputs to a tmp dir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_root = Path(self._tmp.name)
        self._json = self._tmp_root / "system_activation_status_latest.json"
        self._md = self._tmp_root / "SYSTEM_ACTIVATION_STATUS.md"
        self._prev = {
            "SYSTEM_ACTIVATION_STATUS_OUT_JSON":
                os.environ.pop("SYSTEM_ACTIVATION_STATUS_OUT_JSON", None),
            "SYSTEM_ACTIVATION_STATUS_OUT_MD":
                os.environ.pop("SYSTEM_ACTIVATION_STATUS_OUT_MD", None),
        }
        os.environ["SYSTEM_ACTIVATION_STATUS_OUT_JSON"] = str(self._json)
        os.environ["SYSTEM_ACTIVATION_STATUS_OUT_MD"] = str(self._md)
        self.dashboard = _load_dashboard_module()

    def tearDown(self):
        for k, v in self._prev.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        self._tmp.cleanup()


class TestDashboardSubsystemCoverage(_IsolatedEnv):

    def test_01_dashboard_lists_all_20_subsystems(self):
        # Catalogue length is 20 per ETAP 10 spec.
        self.assertEqual(len(self.dashboard.SUBSYSTEMS), 20)

    def test_02_payload_subsystems_match_catalogue_length(self):
        payload = self.dashboard.build_status_payload()
        self.assertEqual(len(payload["subsystems"]), 20)


class TestTopLevelFlags(_IsolatedEnv):

    def test_03_whole_solution_safe_on_is_true(self):
        payload = self.dashboard.build_status_payload()
        self.assertTrue(payload["flags"]["WHOLE_SOLUTION_SAFE_ON"])

    def test_04_trading_execution_on_is_always_false(self):
        payload = self.dashboard.build_status_payload()
        self.assertFalse(payload["flags"]["TRADING_EXECUTION_ON"])
        # Spec-mandated literal in the source — not a runtime computation.
        src = (_REPO_ROOT / "scripts" / "build_system_activation_status.py"
               ).read_text(encoding="utf-8")
        self.assertIn("TRADING_EXECUTION_ON = False", src)

    def test_05_llm_execution_authority_is_always_false(self):
        payload = self.dashboard.build_status_payload()
        self.assertFalse(payload["flags"]["LLM_EXECUTION_AUTHORITY"])
        src = (_REPO_ROOT / "scripts" / "build_system_activation_status.py"
               ).read_text(encoding="utf-8")
        self.assertIn("LLM_EXECUTION_AUTHORITY = False", src)

    def test_06_operator_action_required_true_when_blockers_exist(self):
        # Inject a synthetic blocker via monkey-patched evaluate().
        class _FakeResult:
            class _D:
                value = "ALLOCATOR_BLOCKED_SAFE_MODE_INCONSISTENT"
            decision = _D()
            blockers = ("safe_mode_consistency=INCONSISTENT_ENTERED_NOT_PERSISTED",)
            enabled_subsystems = ()
            llm_status = "unavailable"
            snapshot = {}
        # patch the imported symbol inside the dashboard module
        import system_activation_gate as gate  # noqa
        self.dashboard.__dict__.setdefault("system_activation_gate", gate)
        old = gate.evaluate
        try:
            gate.evaluate = lambda: _FakeResult()  # type: ignore
            payload = self.dashboard.build_status_payload()
        finally:
            gate.evaluate = old
        self.assertTrue(payload["flags"]["OPERATOR_ACTION_REQUIRED"])
        self.assertFalse(payload["flags"]["ALLOCATOR_ALLOWED"])


class TestStandingMarkersAndOutputs(_IsolatedEnv):

    def test_07_standing_markers_present_in_payload(self):
        payload = self.dashboard.build_status_payload()
        for m in (
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
            "NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT",
        ):
            self.assertIn(m, payload["standing_markers"])

    def test_08_main_writes_outputs(self):
        rc = self.dashboard.main()
        self.assertEqual(rc, 0)
        self.assertTrue(self._json.exists())
        self.assertTrue(self._md.exists())
        body = json.loads(self._json.read_text(encoding="utf-8"))
        # v3.30 (2026-06-16): dashboard schema bumped to v3.30 with the
        # close-loop integration. Old v3.29 schema is back-compat only —
        # the test now accepts either string to keep the regression CI
        # signal informative while the new tests check the v3.30 fields.
        self.assertIn(body["schema_version"], {"v3.29", "v3.30"})
        md_text = self._md.read_text(encoding="utf-8")
        self.assertIn("SYSTEM ACTIVATION STATUS", md_text)
        for m in (
            "EDGE_GATE_ENABLED=false",
            "LIVE_TRADING_UNSUPPORTED",
        ):
            self.assertIn(m, md_text)


class TestAstNoBroker(_IsolatedEnv):

    def test_09_ast_no_alpaca_import(self):
        src = (_REPO_ROOT / "scripts" / "build_system_activation_status.py"
               ).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn(
                        a.name, {"alpaca_orders", "shared.alpaca_orders"})
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn(
                    node.module, {"alpaca_orders", "shared.alpaca_orders"})

    def test_10_ast_no_broker_calls(self):
        src = (_REPO_ROOT / "scripts" / "build_system_activation_status.py"
               ).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fname = ""
                if isinstance(node.func, ast.Attribute):
                    fname = node.func.attr
                elif isinstance(node.func, ast.Name):
                    fname = node.func.id
                self.assertNotIn(fname, {
                    "submit_order", "place_order", "safe_close",
                    "cancel_order", "close_position",
                    "place_stock_order", "place_crypto_order",
                    "place_option_order",
                })


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
