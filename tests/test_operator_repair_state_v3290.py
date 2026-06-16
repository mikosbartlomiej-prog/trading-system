"""v3.29 ETAP 1 (2026-06-16) — tests for shared/operator_repair_state.py and CLI.

Asserts:

* default dry-run prints payload + writes nothing,
* ``--operator-confirmed`` writes the marker,
* no broker call,
* no flag flipped,
* marker schema,
* ``load_marker`` returns None when missing,
* ``has_repair_confirmation`` reflects state,
* AST contains no ``alpaca_orders`` import,
* CLI never calls safe_mode clear / broker / order placement,
* standing markers present.
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


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


def _load_cli_module():
    """Load the CLI script as a module."""
    script_path = _REPO_ROOT / "scripts" / "record_operator_repair_confirmation.py"
    if "record_operator_repair_confirmation" in sys.modules:
        del sys.modules["record_operator_repair_confirmation"]
    spec = importlib.util.spec_from_file_location(
        "record_operator_repair_confirmation", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["record_operator_repair_confirmation"] = module
    spec.loader.exec_module(module)
    return module


class _IsolatedEnv(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._markers_dir = Path(self._tmp.name) / "operator_markers"
        self._audit_dir = Path(self._tmp.name) / "audit"
        self._markers_dir.mkdir(parents=True, exist_ok=True)
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        self._prev_markers = os.environ.pop("OPERATOR_MARKERS_DIR", None)
        self._prev_audit = os.environ.pop("AUDIT_TRADING_DIR", None)
        os.environ["OPERATOR_MARKERS_DIR"] = str(self._markers_dir)
        os.environ["AUDIT_TRADING_DIR"] = str(self._audit_dir)
        # Force re-import after env tweak.
        if "operator_repair_state" in sys.modules:
            del sys.modules["operator_repair_state"]
        import operator_repair_state as ors  # noqa
        self.ors = ors

    def tearDown(self):
        os.environ.pop("OPERATOR_MARKERS_DIR", None)
        os.environ.pop("AUDIT_TRADING_DIR", None)
        if self._prev_markers is not None:
            os.environ["OPERATOR_MARKERS_DIR"] = self._prev_markers
        if self._prev_audit is not None:
            os.environ["AUDIT_TRADING_DIR"] = self._prev_audit
        self._tmp.cleanup()


class TestOperatorRepairStateModule(_IsolatedEnv):

    def test_01_load_marker_returns_none_when_missing(self):
        self.assertIsNone(self.ors.load_marker("AVAXUSD"))

    def test_02_write_marker_persists_and_schema_complete(self):
        payload = self.ors.OperatorRepairConfirmation(
            symbol="AVAXUSD",
            incident_type="P13_BRACKET_INTERLOCK",
            dashboard_checked=True,
            open_orders_checked=True,
            stale_oco_cancelled_by_operator="true",
            position_closed_by_operator="true",
            final_position_state="qty=0",
            final_open_orders_state="none",
            equity_checked=True,
            operator_note="manual fix at 12:14 UTC",
            timestamp_iso="2026-06-16T12:14:00+00:00",
        )
        path = self.ors.write_marker(payload)
        self.assertTrue(path.exists())
        raw = json.loads(path.read_text())
        # Required schema fields are all present.
        for field in [
            "symbol", "incident_type", "dashboard_checked", "open_orders_checked",
            "stale_oco_cancelled_by_operator", "position_closed_by_operator",
            "final_position_state", "final_open_orders_state", "equity_checked",
            "operator_note", "timestamp_iso", "source", "does_not_execute_orders",
        ]:
            self.assertIn(field, raw, f"missing schema field {field}")
        # source + does_not_execute_orders ALWAYS forced.
        self.assertEqual(raw["source"], self.ors.MARKER_SOURCE)
        self.assertIs(raw["does_not_execute_orders"], True)

    def test_03_load_marker_round_trips(self):
        payload = self.ors.OperatorRepairConfirmation(
            symbol="AVAXUSD", incident_type="P13",
            dashboard_checked=True, open_orders_checked=True,
            stale_oco_cancelled_by_operator="true",
            position_closed_by_operator="true",
            final_position_state="qty=0",
            final_open_orders_state="none",
            equity_checked=True,
            operator_note="round-trip", timestamp_iso="2026-06-16T12:00:00+00:00",
        )
        self.ors.write_marker(payload)
        loaded = self.ors.load_marker("AVAXUSD")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.symbol, "AVAXUSD")
        self.assertEqual(loaded.operator_note, "round-trip")
        self.assertEqual(loaded.source, self.ors.MARKER_SOURCE)
        self.assertIs(loaded.does_not_execute_orders, True)

    def test_04_has_repair_confirmation_reflects_state(self):
        self.assertFalse(self.ors.has_repair_confirmation("AVAXUSD"))
        payload = self.ors.OperatorRepairConfirmation(
            symbol="AVAXUSD", incident_type="P13",
            dashboard_checked=True, open_orders_checked=True,
            stale_oco_cancelled_by_operator="true",
            position_closed_by_operator="true",
            final_position_state="qty=0", final_open_orders_state="none",
            equity_checked=True, operator_note="",
            timestamp_iso="2026-06-16T12:00:00+00:00",
        )
        self.ors.write_marker(payload)
        self.assertTrue(self.ors.has_repair_confirmation("AVAXUSD"))
        # since_iso in the future → not fresh enough.
        self.assertFalse(self.ors.has_repair_confirmation(
            "AVAXUSD", since_iso="2027-01-01T00:00:00+00:00"))
        # since_iso in the past → fresh enough.
        self.assertTrue(self.ors.has_repair_confirmation(
            "AVAXUSD", since_iso="2026-06-01T00:00:00+00:00"))

    def test_05_standing_markers_present(self):
        m = self.ors.standing_markers()
        for required in [
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
            "NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE",
        ]:
            self.assertIn(required, m)

    def test_06_ast_no_alpaca_orders_import(self):
        path = _REPO_ROOT / "shared" / "operator_repair_state.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden = {"alpaca_orders", "shared.alpaca_orders"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertNotIn(n.name, forbidden)
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, forbidden)

    def test_07_no_broker_or_safe_mode_calls(self):
        """Ensure module never references broker-call symbols or clears safe_mode."""
        path = _REPO_ROOT / "shared" / "operator_repair_state.py"
        src = path.read_text(encoding="utf-8")
        # Strip docstrings + comments to avoid hitting explanatory text.
        tree = ast.parse(src)
        forbidden_calls = {
            "submit_order", "place_order", "safe_close",
            "cancel_order", "close_position", "place_stock_order",
            "place_crypto_order", "place_option_order",
            "exit_safe_mode",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = (getattr(func, "attr", None)
                        or getattr(func, "id", None) or "")
                self.assertNotIn(name, forbidden_calls,
                                 f"forbidden call {name} in operator_repair_state")

    def test_08_invariant_constants_at_module_level(self):
        # All invariant constants present and have safe values.
        self.assertIs(self.ors.LIVE_TRADING_UNSUPPORTED, True)
        self.assertIs(self.ors.NO_ORDER_PLACEMENT, True)
        self.assertIs(self.ors.NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE, True)
        self.assertIs(self.ors.EDGE_GATE_ENABLED, False)
        self.assertIs(self.ors.ALLOW_BROKER_PAPER, False)

    def test_09_write_marker_normalizes_source_even_if_overridden(self):
        # Construct manually with bogus source; from_dict normalizes
        # to MARKER_SOURCE on reload (write_marker enforces via _normalize).
        payload = self.ors.OperatorRepairConfirmation(
            symbol="AVAXUSD", incident_type="P13",
            dashboard_checked=True, open_orders_checked=True,
            stale_oco_cancelled_by_operator="true",
            position_closed_by_operator="true",
            final_position_state="qty=0", final_open_orders_state="none",
            equity_checked=True, operator_note="",
            timestamp_iso="2026-06-16T12:00:00+00:00",
            source="ATTACKER_OVERRIDE", does_not_execute_orders=False,
        )
        path = self.ors.write_marker(payload)
        raw = json.loads(path.read_text())
        self.assertEqual(raw["source"], self.ors.MARKER_SOURCE)
        self.assertIs(raw["does_not_execute_orders"], True)

    def test_10_list_markers_returns_dict_keyed_by_symbol(self):
        for sym in ("AVAXUSD", "ETHUSD"):
            self.ors.write_marker(self.ors.OperatorRepairConfirmation(
                symbol=sym, incident_type="P13",
                dashboard_checked=True, open_orders_checked=True,
                stale_oco_cancelled_by_operator="true",
                position_closed_by_operator="true",
                final_position_state="qty=0", final_open_orders_state="none",
                equity_checked=True, operator_note="",
                timestamp_iso="2026-06-16T12:00:00+00:00",
            ))
        markers = self.ors.list_markers()
        self.assertIn("AVAXUSD", markers)
        self.assertIn("ETHUSD", markers)


class TestRecordOperatorRepairConfirmationCLI(_IsolatedEnv):

    def test_11_default_dry_run_writes_nothing(self):
        cli = _load_cli_module()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main([
                "--symbol", "AVAXUSD",
                "--dashboard-checked",
                "--open-orders-checked",
                "--stale-oco-cancelled", "true",
                "--position-closed", "true",
                "--equity-checked",
                # NO --operator-confirmed → dry-run by default
            ])
        self.assertEqual(rc, 0)
        text = buf.getvalue()
        self.assertIn("Dry run", text)
        # No marker file created.
        self.assertEqual(list(self._markers_dir.glob("*.json")), [])

    def test_12_operator_confirmed_writes_marker(self):
        cli = _load_cli_module()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main([
                "--symbol", "AVAXUSD",
                "--dashboard-checked",
                "--open-orders-checked",
                "--stale-oco-cancelled", "true",
                "--position-closed", "true",
                "--equity-checked",
                "--operator-note", "manually fixed AVAX dust",
                "--operator-confirmed",
            ])
        self.assertEqual(rc, 0)
        files = list(self._markers_dir.glob("AVAXUSD_*.json"))
        self.assertEqual(len(files), 1)
        raw = json.loads(files[0].read_text())
        self.assertEqual(raw["symbol"], "AVAXUSD")
        self.assertIs(raw["does_not_execute_orders"], True)

    def test_13_cli_dry_run_forced_overrides_confirmed(self):
        cli = _load_cli_module()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main([
                "--symbol", "AVAXUSD",
                "--operator-confirmed",
                "--dry-run", "true",
            ])
        self.assertEqual(rc, 0)
        self.assertEqual(list(self._markers_dir.glob("*.json")), [])

    def test_14_cli_ast_no_alpaca_orders(self):
        path = _REPO_ROOT / "scripts" / "record_operator_repair_confirmation.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden = {"alpaca_orders", "shared.alpaca_orders"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertNotIn(n.name, forbidden)
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, forbidden)

    def test_15_cli_never_clears_safe_mode(self):
        path = _REPO_ROOT / "scripts" / "record_operator_repair_confirmation.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = (getattr(node.func, "attr", None)
                        or getattr(node.func, "id", None) or "")
                self.assertNotIn(name, {"exit_safe_mode", "clear_repair"},
                                 f"CLI forbidden to call {name}")


if __name__ == "__main__":
    unittest.main()
