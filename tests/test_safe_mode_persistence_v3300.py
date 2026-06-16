"""v3.30 ETAP 4 (2026-06-16) — tests for shared/safe_mode_state.py.

Coverage:
- enter() writes both files atomically
- duplicate enter() within dedupe window is a no-op (no double-write)
- write failure raises SafeModeStateWriteFailed (fail-CLOSED)
- audit/state mismatch emits SAFE_MODE_STATE_RECOVERY_REQUIRED
- no auto-clear API exists (no exit/clear function)
- module never imports alpaca_orders (AST verified)
- module never calls broker functions (AST verified)
"""

from __future__ import annotations

import ast
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.state_path = self.tmp / "safe_mode_state.json"
        self.audit_dir = self.tmp / "audit"
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_path = self.tmp / "runtime_state.json"

        os.environ["SAFE_MODE_STATE_PATH"] = str(self.state_path)
        os.environ["AUDIT_TRADING_DIR"] = str(self.audit_dir)
        os.environ["RUNTIME_STATE_PATH"] = str(self.runtime_path)

        # Fresh import each test so module-level path resolution picks
        # up the env vars above.
        for mod in (
            "safe_mode_state",
            "runtime_state",
        ):
            sys.modules.pop(mod, None)

    def tearDown(self) -> None:
        for var in ("SAFE_MODE_STATE_PATH", "AUDIT_TRADING_DIR", "RUNTIME_STATE_PATH"):
            os.environ.pop(var, None)
        self._tmpdir.cleanup()


class TestEnterWritesBothFilesAtomically(_Base):
    def test_first_enter_writes_canonical_file(self) -> None:
        import safe_mode_state as sms
        state = sms.enter(
            trigger="INCIDENT_P13_BRACKET_INTERLOCK",
            reason="initial test enter",
            symbol="AVAX/USD",
        )
        self.assertTrue(state.active)
        self.assertEqual(state.trigger, "INCIDENT_P13_BRACKET_INTERLOCK")
        self.assertEqual(state.symbol, "AVAX/USD")
        self.assertTrue(self.state_path.exists())
        raw = json.loads(self.state_path.read_text())
        self.assertTrue(raw["active"])
        self.assertEqual(raw["trigger"], "INCIDENT_P13_BRACKET_INTERLOCK")
        self.assertEqual(raw["symbol"], "AVAX/USD")
        self.assertEqual(raw["schema_version"], "v3.30")

    def test_first_enter_mirrors_to_runtime_state(self) -> None:
        import safe_mode_state as sms
        sms.enter(
            trigger="ACCOUNT_OUTAGE",
            reason="alpaca down",
            symbol="",
        )
        # runtime mirror best-effort. If runtime_state.write_section worked,
        # the file should exist with a safe_mode section.
        self.assertTrue(self.runtime_path.exists())
        raw = json.loads(self.runtime_path.read_text())
        self.assertIn("safe_mode", raw)
        self.assertTrue(raw["safe_mode"]["active"])
        self.assertEqual(raw["safe_mode"]["trigger"], "ACCOUNT_OUTAGE")

    def test_atomic_write_uses_tmp_then_replace(self) -> None:
        # Confirm no `.tmp` file remains after a successful write.
        import safe_mode_state as sms
        sms.enter(
            trigger="OPERATOR",
            reason="atomic check",
            symbol="ETH/USD",
        )
        # The .tmp suffix should be gone.
        tmp_file = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        self.assertFalse(tmp_file.exists())
        self.assertTrue(self.state_path.exists())


class TestDuplicateEnterDedupes(_Base):
    def test_same_trigger_same_symbol_within_window_returns_existing(self) -> None:
        import safe_mode_state as sms
        first = sms.enter(
            trigger="INCIDENT_P13_BRACKET_INTERLOCK",
            reason="first enter",
            symbol="AVAX/USD",
        )
        # mtime BEFORE second call.
        mtime_first = self.state_path.stat().st_mtime_ns

        second = sms.enter(
            trigger="INCIDENT_P13_BRACKET_INTERLOCK",
            reason="duplicate within dedupe window",
            symbol="AVAX/USD",
        )
        # Same entered_at_iso, dedupe should result in no second write.
        self.assertEqual(second.entered_at_iso, first.entered_at_iso)
        # The reason should remain the FIRST reason (no overwrite).
        self.assertEqual(second.reason, first.reason)
        mtime_second = self.state_path.stat().st_mtime_ns
        # File should not have been re-written (within OS clock resolution we
        # just check mtime did not change).
        self.assertEqual(mtime_first, mtime_second)

    def test_different_symbol_does_not_dedupe(self) -> None:
        import safe_mode_state as sms
        sms.enter(
            trigger="INCIDENT_P13_BRACKET_INTERLOCK",
            reason="first symbol",
            symbol="AVAX/USD",
        )
        # Different symbol = fresh write.
        second = sms.enter(
            trigger="INCIDENT_P13_BRACKET_INTERLOCK",
            reason="second symbol",
            symbol="ETH/USD",
        )
        self.assertEqual(second.symbol, "ETH/USD")
        raw = json.loads(self.state_path.read_text())
        self.assertEqual(raw["symbol"], "ETH/USD")

    def test_different_trigger_does_not_dedupe(self) -> None:
        import safe_mode_state as sms
        sms.enter(
            trigger="INCIDENT_P13_BRACKET_INTERLOCK",
            reason="first trigger",
            symbol="AVAX/USD",
        )
        second = sms.enter(
            trigger="ACCOUNT_OUTAGE",
            reason="second trigger",
            symbol="AVAX/USD",
        )
        self.assertEqual(second.trigger, "ACCOUNT_OUTAGE")


class TestWriteFailureFailsClosed(_Base):
    def test_atomic_write_failure_raises_and_emits_audit(self) -> None:
        import safe_mode_state as sms

        def _broken_atomic_write(*args, **kwargs):
            raise sms.SafeModeStateWriteFailed("simulated disk full")

        with mock.patch.object(sms, "_atomic_write_json", _broken_atomic_write):
            with self.assertRaises(sms.SafeModeStateWriteFailed):
                sms.enter(
                    trigger="INCIDENT_P13_BRACKET_INTERLOCK",
                    reason="simulated failure",
                    symbol="AVAX/USD",
                )

        # Audit row SHOULD have been written.
        audit_files = list(self.audit_dir.glob("*.jsonl"))
        self.assertTrue(audit_files, "no audit file written after failure")
        rows = [
            json.loads(line)
            for af in audit_files
            for line in af.read_text().splitlines()
            if line.strip()
        ]
        write_failed = [
            r for r in rows if r.get("decision_type") == "SAFE_MODE_STATE_WRITE_FAILED"
        ]
        self.assertTrue(
            write_failed,
            f"expected SAFE_MODE_STATE_WRITE_FAILED in audit, got {rows}",
        )


class TestConsistencyMismatch(_Base):
    def test_recovery_required_when_audit_says_active_but_state_says_inactive(self) -> None:
        # Setup: write a runtime mirror with active=True but DO NOT write the
        # canonical state file. This simulates the v3.29 persistence bug.
        self.runtime_path.write_text(json.dumps({
            "safe_mode": {
                "active": True,
                "trigger": "INCIDENT_P13_BRACKET_INTERLOCK",
                "reason": "mirror says active but canonical does not",
                "entered_at": "2026-06-16T00:00:00+00:00",
                "forced": False,
            }
        }))

        import safe_mode_state as sms
        report = sms.check_consistency_with_audit()
        self.assertFalse(report["canonical_active"])
        self.assertTrue(report["mirror_active"])
        self.assertFalse(report["consistent"])
        self.assertTrue(report["recovery_required"])

        # Audit row should be emitted.
        audit_files = list(self.audit_dir.glob("*.jsonl"))
        self.assertTrue(audit_files)
        rows = [
            json.loads(line)
            for af in audit_files
            for line in af.read_text().splitlines()
            if line.strip()
        ]
        recovery = [
            r for r in rows if r.get("decision_type") == "SAFE_MODE_STATE_RECOVERY_REQUIRED"
        ]
        self.assertTrue(recovery, f"expected SAFE_MODE_STATE_RECOVERY_REQUIRED, got {rows}")

    def test_consistent_when_both_active(self) -> None:
        import safe_mode_state as sms
        # Write canonical state via the public API.
        sms.enter(
            trigger="INCIDENT_P13_BRACKET_INTERLOCK",
            reason="both active",
            symbol="AVAX/USD",
        )
        # Re-verify consistency: mirror was written by enter().
        report = sms.check_consistency_with_audit()
        self.assertTrue(report["canonical_active"])
        self.assertTrue(report["mirror_active"])
        self.assertTrue(report["consistent"])
        self.assertFalse(report["recovery_required"])

    def test_no_recovery_when_both_inactive(self) -> None:
        import safe_mode_state as sms
        report = sms.check_consistency_with_audit()
        self.assertFalse(report["canonical_active"])
        self.assertFalse(report["mirror_active"])
        self.assertTrue(report["consistent"])
        self.assertFalse(report["recovery_required"])


class TestNoAutoClearFromAnyCodePath(_Base):
    def test_no_exit_or_clear_function_exported(self) -> None:
        import safe_mode_state as sms
        public = set(sms.__all__)
        forbidden = {"exit", "exit_safe_mode", "clear", "clear_safe_mode",
                     "deactivate", "force_inactive", "reset"}
        self.assertFalse(
            public & forbidden,
            f"safe_mode_state.py must NOT export any auto-clear API; got {public & forbidden}",
        )

    def test_is_active_takes_union_of_canonical_and_mirror(self) -> None:
        """When mirror says active but canonical does not, is_active() must
        return True. This proves the fail-CLOSED union contract that
        survives the v3.29 persistence bug.
        """
        self.runtime_path.write_text(json.dumps({
            "safe_mode": {
                "active": True,
                "trigger": "INCIDENT_P13_BRACKET_INTERLOCK",
                "reason": "mirror only",
                "entered_at": "2026-06-16T00:00:00+00:00",
                "forced": False,
            }
        }))
        import safe_mode_state as sms
        self.assertTrue(sms.is_active())


class TestNoBrokerImports(unittest.TestCase):
    """Static AST scan — safe_mode_state must NEVER import alpaca_orders
    and must NEVER call broker functions.
    """

    def setUp(self) -> None:
        path = _REPO_ROOT / "shared" / "safe_mode_state.py"
        with open(path, "r", encoding="utf-8") as fh:
            self.tree = ast.parse(fh.read())

    def test_no_alpaca_orders_import(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("alpaca_orders", alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module is not None:
                    self.assertNotIn("alpaca_orders", node.module)

    def test_no_broker_function_calls(self) -> None:
        forbidden_names = {
            "submit_order", "place_order", "safe_close", "cancel_order",
            "close_position", "place_stock_bracket", "place_crypto_order",
            "place_simple_buy", "place_options_buy",
        }
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                func = node.func
                fn_name = None
                if isinstance(func, ast.Name):
                    fn_name = func.id
                elif isinstance(func, ast.Attribute):
                    fn_name = func.attr
                if fn_name and fn_name in forbidden_names:
                    self.fail(
                        f"safe_mode_state.py contains forbidden broker call: {fn_name}"
                    )


if __name__ == "__main__":
    unittest.main()
