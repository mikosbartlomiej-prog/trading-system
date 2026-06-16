"""v3.30 ETAP 11 (2026-06-16) — Activation dashboard close-loop tests.

Asserts the v3.30 top-level flag set the dashboard MUST emit:

* All required v3.30 top-level fields present.
* ``TRADING_EXECUTION_ON`` is a write-time literal ``False``.
* ``LLM_EXECUTION_AUTHORITY`` is a write-time literal ``False``.
* ``BROKER_REPAIR_GUARD_WIRED_IN_SAFE_CLOSE`` truthful re: post-v3.30
  safe_close source.
* ``RETRY_STORM_SUPPRESSION_ACTIVE`` truthful.
* ``OPERATOR_ACTION_REQUIRED`` True iff blockers present.
* ``LLM_PROVIDER_MODE`` is one of {REAL_PROVIDER, DETERMINISTIC_FALLBACK,
  UNAVAILABLE}.
* ``NEXT_OPERATOR_ACTIONS`` non-empty when blocked.
* ``BLOCKERS`` list matches master gate output.
* AST: no ``alpaca_orders`` import.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


REQUIRED_FLAGS = (
    "WHOLE_SAFE_STACK_ON",
    "TRADING_EXECUTION_ON",
    "ALLOCATOR_ALLOWED",
    "SHADOW_ONLY_ALLOWED",
    "LLM_ADVISORY_ON",
    "LLM_PROVIDER_MODE",
    "LLM_EXECUTION_AUTHORITY",
    "BROKER_REPAIR_GUARD_WIRED_IN_SAFE_CLOSE",
    "RETRY_STORM_SUPPRESSION_ACTIVE",
    "SAFE_MODE_CONSISTENCY_CHECK_ACTIVE",
    "OPERATOR_ACTION_REQUIRED",
    "BLOCKERS",
    "NEXT_OPERATOR_ACTIONS",
)


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


class _FakeResult:
    class _D:
        value = "ALLOCATOR_BLOCKED_BROKER_REPAIR"
    decision = _D()
    blockers = ("broker_repair_required:AVAX/USD",)
    enabled_subsystems = ()
    llm_status = "advisory_on"
    snapshot = {
        "retry_storm_active": False,
        "fresh_p13_in_window": False,
    }
    shadow_only_allowed = True


class _FakeResultAllowed:
    class _D:
        value = "ALLOCATOR_ALLOWED"
    decision = _D()
    blockers = ()
    enabled_subsystems = ()
    llm_status = "advisory_on"
    snapshot = {
        "retry_storm_active": False,
        "fresh_p13_in_window": False,
    }
    shadow_only_allowed = True


# ── 1. All required v3.30 fields present ─────────────────────────────────────

class TestAllRequiredFlagsPresent(_IsolatedEnv):

    def test_01_required_flags_present_in_payload(self):
        import system_activation_gate as gate
        old = gate.evaluate
        try:
            gate.evaluate = lambda: _FakeResult()  # type: ignore
            payload = self.dashboard.build_status_payload()
        finally:
            gate.evaluate = old
        for k in REQUIRED_FLAGS:
            self.assertIn(k, payload["flags"], f"missing flag: {k}")


# ── 2. Literal hard-coded invariants ─────────────────────────────────────────

class TestLiteralInvariants(_IsolatedEnv):

    def test_02_trading_execution_on_hardcoded_false(self):
        src = (_REPO_ROOT / "scripts"
                / "build_system_activation_status.py").read_text(encoding="utf-8")
        self.assertIn("TRADING_EXECUTION_ON = False", src)
        # And at runtime the flag must be False.
        import system_activation_gate as gate
        old = gate.evaluate
        try:
            gate.evaluate = lambda: _FakeResult()  # type: ignore
            payload = self.dashboard.build_status_payload()
        finally:
            gate.evaluate = old
        self.assertFalse(payload["flags"]["TRADING_EXECUTION_ON"])

    def test_03_llm_execution_authority_hardcoded_false(self):
        src = (_REPO_ROOT / "scripts"
                / "build_system_activation_status.py").read_text(encoding="utf-8")
        self.assertIn("LLM_EXECUTION_AUTHORITY = False", src)
        import system_activation_gate as gate
        old = gate.evaluate
        try:
            gate.evaluate = lambda: _FakeResult()  # type: ignore
            payload = self.dashboard.build_status_payload()
        finally:
            gate.evaluate = old
        self.assertFalse(payload["flags"]["LLM_EXECUTION_AUTHORITY"])


# ── 3. Wired-guard flag truthful ─────────────────────────────────────────────

class TestBrokerRepairGuardWiredFlag(_IsolatedEnv):

    def test_04_broker_repair_guard_wired_true_in_v330(self):
        import system_activation_gate as gate
        old = gate.evaluate
        try:
            gate.evaluate = lambda: _FakeResult()  # type: ignore
            payload = self.dashboard.build_status_payload()
        finally:
            gate.evaluate = old
        self.assertTrue(payload["flags"]["BROKER_REPAIR_GUARD_WIRED_IN_SAFE_CLOSE"])

    def test_05_retry_storm_suppression_active_true(self):
        import system_activation_gate as gate
        old = gate.evaluate
        try:
            gate.evaluate = lambda: _FakeResult()  # type: ignore
            payload = self.dashboard.build_status_payload()
        finally:
            gate.evaluate = old
        self.assertTrue(payload["flags"]["RETRY_STORM_SUPPRESSION_ACTIVE"])


# ── 4. Operator-action behaviour ─────────────────────────────────────────────

class TestOperatorActionBehaviour(_IsolatedEnv):

    def test_06_operator_action_required_when_blockers_exist(self):
        import system_activation_gate as gate
        old = gate.evaluate
        try:
            gate.evaluate = lambda: _FakeResult()  # type: ignore
            payload = self.dashboard.build_status_payload()
        finally:
            gate.evaluate = old
        self.assertTrue(payload["flags"]["OPERATOR_ACTION_REQUIRED"])
        self.assertTrue(payload["flags"]["NEXT_OPERATOR_ACTIONS"],
                          "NEXT_OPERATOR_ACTIONS must be non-empty when blocked")

    def test_07_next_operator_actions_empty_when_allowed(self):
        import system_activation_gate as gate
        old = gate.evaluate
        try:
            gate.evaluate = lambda: _FakeResultAllowed()  # type: ignore
            payload = self.dashboard.build_status_payload()
        finally:
            gate.evaluate = old
        self.assertFalse(payload["flags"]["OPERATOR_ACTION_REQUIRED"])
        self.assertEqual(payload["flags"]["NEXT_OPERATOR_ACTIONS"], [])

    def test_08_blockers_list_matches_gate_output(self):
        import system_activation_gate as gate
        old = gate.evaluate
        try:
            gate.evaluate = lambda: _FakeResult()  # type: ignore
            payload = self.dashboard.build_status_payload()
        finally:
            gate.evaluate = old
        self.assertEqual(payload["flags"]["BLOCKERS"],
                          ["broker_repair_required:AVAX/USD"])


# ── 5. LLM provider mode enum ────────────────────────────────────────────────

class TestLLMProviderMode(_IsolatedEnv):

    def test_09_llm_provider_mode_one_of_three_values(self):
        import system_activation_gate as gate
        old = gate.evaluate
        try:
            gate.evaluate = lambda: _FakeResult()  # type: ignore
            payload = self.dashboard.build_status_payload()
        finally:
            gate.evaluate = old
        self.assertIn(
            payload["flags"]["LLM_PROVIDER_MODE"],
            {"REAL_PROVIDER", "DETERMINISTIC_FALLBACK", "UNAVAILABLE"},
        )


# ── 6. AST no alpaca ─────────────────────────────────────────────────────────

class TestAstNoAlpaca(unittest.TestCase):

    def test_10_ast_no_alpaca_import_in_dashboard(self):
        src = (_REPO_ROOT / "scripts"
                / "build_system_activation_status.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn(
                        a.name, {"alpaca_orders", "shared.alpaca_orders"})
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn(
                    node.module, {"alpaca_orders", "shared.alpaca_orders"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
