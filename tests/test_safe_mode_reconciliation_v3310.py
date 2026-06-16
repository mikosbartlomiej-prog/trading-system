"""v3.31 ETAP 3 (2026-06-16) — tests for scripts/propose_safe_mode_reconciliation.py.

Asserts:

* no markers → ``RECONCILIATION_BLOCKED_OPERATOR_MARKER_REQUIRED``
* markers + fresh P13 after marker → ``RECONCILIATION_BLOCKED_FRESH_INCIDENT``
* markers + equity gap → ``RECONCILIATION_BLOCKED_EQUITY_GAP``
* all clear dry-run → ``RECONCILIATION_READY_TO_PROPOSE``
* ``--apply --operator-confirmed`` → ``RECONCILIATION_PROPOSAL_WRITTEN``
* proposal file content references ``Operator:`` not ``System:`` (manual only)
* never auto-applies (writing proposal does NOT mutate state)
* AST: no ``alpaca_orders`` import
* preserves audit row historically (does not delete)
* standing markers footer in proposal file
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


def _load_script():
    script_path = _REPO_ROOT / "scripts" / "propose_safe_mode_reconciliation.py"
    if "propose_safe_mode_reconciliation" in sys.modules:
        del sys.modules["propose_safe_mode_reconciliation"]
    spec = importlib.util.spec_from_file_location(
        "propose_safe_mode_reconciliation", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["propose_safe_mode_reconciliation"] = module
    spec.loader.exec_module(module)
    return module


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


class _IsolatedEnv(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._audit_dir = tmp / "audit"
        self._markers_dir = tmp / "operator_markers"
        self._brr_path = tmp / "broker_repair_required_latest.json"
        self._runtime_state_path = tmp / "runtime_state.json"
        self._safe_mode_state_path = tmp / "safe_mode_state.json"
        self._equity_gap_path = tmp / "equity_gap_reconciliation_latest.json"
        for p in (self._audit_dir, self._markers_dir):
            p.mkdir(parents=True, exist_ok=True)
        self._prev = {}
        for k in ("AUDIT_TRADING_DIR", "OPERATOR_MARKERS_DIR",
                  "BROKER_REPAIR_REQUIRED_PATH", "RUNTIME_STATE_PATH",
                  "SAFE_MODE_STATE_PATH", "EQUITY_GAP_PATH"):
            self._prev[k] = os.environ.pop(k, None)
        os.environ["AUDIT_TRADING_DIR"]               = str(self._audit_dir)
        os.environ["OPERATOR_MARKERS_DIR"]            = str(self._markers_dir)
        os.environ["BROKER_REPAIR_REQUIRED_PATH"]     = str(self._brr_path)
        os.environ["RUNTIME_STATE_PATH"]              = str(self._runtime_state_path)
        os.environ["SAFE_MODE_STATE_PATH"]            = str(self._safe_mode_state_path)
        os.environ["EQUITY_GAP_PATH"]                 = str(self._equity_gap_path)
        # Re-import to pick up env changes.
        for mod in ("propose_safe_mode_reconciliation",
                    "broker_repair_required", "operator_repair_state"):
            if mod in sys.modules:
                del sys.modules[mod]
        self.script = _load_script()

    def tearDown(self):
        for k, v in self._prev.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        self._tmp.cleanup()

    def _write_audit_row(self, day: str, row: dict) -> None:
        path = self._audit_dir / f"{day}.jsonl"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    def _write_safe_mode_entered(self, when: datetime,
                                 symbol: str = "AVAX/USD") -> None:
        self._write_audit_row(when.date().isoformat(), {
            "decision_type": "SAFE_MODE_ENTERED",
            "actor":         "incident-pattern-detector",
            "reason":        "P13_BRACKET_INTERLOCK",
            "affected_symbols": [symbol],
            "timestamp":     when.isoformat(),
        })

    def _write_fresh_p13(self, when: datetime, symbol: str = "AVAX/USD") -> None:
        self._write_audit_row(when.date().isoformat(), {
            "decision_type": "INCIDENT_P13_BRACKET_INTERLOCK",
            "actor":         "incident-pattern-detector",
            "reason":        "P13_BRACKET_INTERLOCK retry storm",
            "affected_symbols": [symbol],
            "timestamp":     when.isoformat(),
        })

    def _write_broker_repair_entry(self, symbol: str) -> None:
        body = {
            "schema_version": "v3.28",
            "updated_at": _now_iso(),
            "entries": {
                symbol: {
                    "symbol": symbol,
                    "incident_type": "P13_BRACKET_INTERLOCK",
                    "first_seen_iso": _now_iso(),
                    "last_seen_iso":  _now_iso(),
                    "failed_attempts": 1,
                    "last_error": "Alpaca 403 insufficient balance",
                    "manual_action_required": "operator review",
                    "allowed_next_actions": ["operator_marker_required"],
                    "safe_mode_reason": "P13_BRACKET_INTERLOCK",
                    "retry_after_iso": None,
                    "broker_calls_blocked_until_iso": None,
                },
            },
        }
        with open(self._brr_path, "w", encoding="utf-8") as fh:
            json.dump(body, fh, indent=2, sort_keys=True)

    def _write_equity_gap(self, verdict: str) -> None:
        body = {
            "schema_version":   "v3.28",
            "verdict":          verdict,
            "block_allocator":  verdict != "EQUITY_GAP_OK",
            "generated_at_iso": _now_iso(),
        }
        with open(self._equity_gap_path, "w", encoding="utf-8") as fh:
            json.dump(body, fh, indent=2, sort_keys=True)

    def _write_marker(self, symbol: str, when: datetime) -> None:
        safe = symbol.replace("/", "_")
        path = self._markers_dir / f"{safe}_{when.date().isoformat()}.json"
        body = {
            "symbol": symbol,
            "incident_type": "P13_BRACKET_INTERLOCK",
            "dashboard_checked": True,
            "open_orders_checked": True,
            "stale_oco_cancelled_by_operator": "true",
            "position_closed_by_operator": "true",
            "final_position_state": "qty=0",
            "final_open_orders_state": "none",
            "equity_checked": True,
            "operator_note": "tested manual repair",
            "timestamp_iso": when.isoformat(),
            "source": "OPERATOR_MANUAL_CONFIRMATION",
            "does_not_execute_orders": True,
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(body, fh, indent=2, sort_keys=True)


class TestSafeModeReconciliation(_IsolatedEnv):

    def test_01_no_markers_blocks(self):
        self._write_safe_mode_entered(_now() - timedelta(hours=2))
        self._write_broker_repair_entry("AVAX/USD")
        self._write_equity_gap("EQUITY_GAP_OK")
        result, actions = self.script._evaluate(operator_confirmed=False)
        self.assertEqual(result.verdict,
                         self.script.VERDICT_BLOCKED_OPERATOR_MARKER_REQUIRED)
        self.assertEqual(actions, [])
        self.assertIn("AVAX/USD", result.symbols_without_marker)

    def test_02_markers_plus_fresh_p13_blocks(self):
        # Marker recorded 6h ago, then a fresh P13 fired 1h ago.
        self._write_safe_mode_entered(_now() - timedelta(hours=6))
        self._write_broker_repair_entry("AVAX/USD")
        self._write_marker("AVAX/USD", _now() - timedelta(hours=6))
        self._write_fresh_p13(_now() - timedelta(hours=1))
        self._write_equity_gap("EQUITY_GAP_OK")
        result, actions = self.script._evaluate(operator_confirmed=False)
        self.assertEqual(result.verdict,
                         self.script.VERDICT_BLOCKED_FRESH_INCIDENT)
        self.assertEqual(actions, [])

    def test_03_markers_plus_equity_gap_blocks(self):
        self._write_safe_mode_entered(_now() - timedelta(hours=2))
        self._write_broker_repair_entry("AVAX/USD")
        self._write_marker("AVAX/USD", _now())
        self._write_equity_gap("EQUITY_GAP_UNRESOLVED_BLOCKS_ALLOCATOR")
        result, actions = self.script._evaluate(operator_confirmed=False)
        self.assertEqual(result.verdict,
                         self.script.VERDICT_BLOCKED_EQUITY_GAP)
        self.assertEqual(actions, [])

    def test_04_all_clear_dry_run_ready(self):
        self._write_safe_mode_entered(_now() - timedelta(hours=2))
        self._write_broker_repair_entry("AVAX/USD")
        self._write_marker("AVAX/USD", _now())
        self._write_equity_gap("EQUITY_GAP_OK")
        result, actions = self.script._evaluate(operator_confirmed=False)
        self.assertEqual(result.verdict,
                         self.script.VERDICT_READY_TO_PROPOSE)
        self.assertGreater(len(actions), 0)
        # No proposal file written in dry-run.
        for p in self._markers_dir.glob("safe_mode_reconciliation_proposal_*.json"):
            self.fail(f"unexpected proposal file in dry-run: {p}")

    def test_05_apply_operator_confirmed_writes_proposal(self):
        self._write_safe_mode_entered(_now() - timedelta(hours=2))
        self._write_broker_repair_entry("AVAX/USD")
        self._write_marker("AVAX/USD", _now())
        self._write_equity_gap("EQUITY_GAP_OK")
        # Drive through main() to test the CLI surface.
        rc = self.script.main(["--dry-run", "false",
                               "--apply", "--operator-confirmed"])
        self.assertEqual(rc, 0)
        proposals = list(self._markers_dir.glob(
            "safe_mode_reconciliation_proposal_*.json"))
        self.assertEqual(len(proposals), 1)
        body = json.loads(proposals[0].read_text())
        self.assertEqual(body["verdict"],
                         self.script.VERDICT_READY_TO_PROPOSE)
        # File must exist with proposed_actions list.
        self.assertIn("proposed_actions", body)
        self.assertGreater(len(body["proposed_actions"]), 0)

    def test_06_proposal_content_references_operator_not_system(self):
        self._write_safe_mode_entered(_now() - timedelta(hours=2))
        self._write_broker_repair_entry("AVAX/USD")
        self._write_marker("AVAX/USD", _now())
        self._write_equity_gap("EQUITY_GAP_OK")
        self.script.main(["--dry-run", "false",
                          "--apply", "--operator-confirmed"])
        proposals = list(self._markers_dir.glob(
            "safe_mode_reconciliation_proposal_*.json"))
        body = json.loads(proposals[0].read_text())
        for action in body["proposed_actions"]:
            self.assertNotIn("System:", action,
                             f"action should not start with 'System:': {action}")
        # At least one action must explicitly call out the operator.
        self.assertTrue(any("Operator:" in a for a in body["proposed_actions"]))

    def test_07_never_auto_applies_state(self):
        """Writing the proposal must NOT mutate runtime_state, safe_mode_state,
        broker_repair_required, or remove any audit row."""
        # Pre-write a runtime_state to confirm it's not mutated.
        with open(self._runtime_state_path, "w", encoding="utf-8") as fh:
            json.dump({"safe_mode": {"active": True, "reason": "P13"}}, fh)
        # Same for the audit (one SAFE_MODE_ENTERED row).
        before = _now() - timedelta(hours=2)
        self._write_safe_mode_entered(before)
        audit_file = self._audit_dir / f"{before.date().isoformat()}.jsonl"
        audit_before = audit_file.read_text()
        self._write_broker_repair_entry("AVAX/USD")
        self._write_marker("AVAX/USD", _now())
        self._write_equity_gap("EQUITY_GAP_OK")
        brr_before = self._brr_path.read_text()
        # Run apply.
        # Runtime safe_mode is active → blocks via _evaluate's RULE D
        # check on safe_mode? No — RULE D is "ready"; the script never
        # mutates runtime_state. We instead just verify nothing changed.
        self.script.main(["--dry-run", "false",
                          "--apply", "--operator-confirmed"])
        # Audit row unchanged.
        self.assertEqual(audit_file.read_text(), audit_before)
        # broker_repair_required unchanged.
        self.assertEqual(self._brr_path.read_text(), brr_before)
        # runtime_state unchanged.
        rs = json.loads(self._runtime_state_path.read_text())
        self.assertEqual(rs["safe_mode"], {"active": True, "reason": "P13"})

    def test_08_ast_no_alpaca_orders_import(self):
        path = _REPO_ROOT / "scripts" / "propose_safe_mode_reconciliation.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden = {"alpaca_orders", "shared.alpaca_orders"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertNotIn(n.name, forbidden)
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, forbidden)
        # Also: no forbidden broker calls.
        forbidden_calls = {
            "close_position", "safe_close", "place_order", "submit_order",
            "cancel_order", "place_stock_order", "place_crypto_order",
            "place_option_order", "exit_safe_mode", "clear_repair",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = (getattr(node.func, "attr", None)
                        or getattr(node.func, "id", None) or "")
                self.assertNotIn(name, forbidden_calls,
                                 f"forbidden call {name} in script")

    def test_09_preserves_audit_rows(self):
        """The script reads audit but never writes/deletes audit JSONL files."""
        ts = _now() - timedelta(hours=2)
        self._write_safe_mode_entered(ts)
        self._write_safe_mode_entered(ts + timedelta(minutes=5))
        self._write_safe_mode_entered(ts + timedelta(minutes=10))
        path = self._audit_dir / f"{ts.date().isoformat()}.jsonl"
        before_lines = path.read_text().splitlines()
        self.assertEqual(len(before_lines), 3)
        # Run apply (even though no markers → blocks).
        self.script.main(["--dry-run", "false",
                          "--apply", "--operator-confirmed"])
        after_lines = path.read_text().splitlines()
        self.assertEqual(before_lines, after_lines)

    def test_10_standing_markers_in_proposal(self):
        self._write_safe_mode_entered(_now() - timedelta(hours=2))
        self._write_broker_repair_entry("AVAX/USD")
        self._write_marker("AVAX/USD", _now())
        self._write_equity_gap("EQUITY_GAP_OK")
        self.script.main(["--dry-run", "false",
                          "--apply", "--operator-confirmed"])
        proposals = list(self._markers_dir.glob(
            "safe_mode_reconciliation_proposal_*.json"))
        body = json.loads(proposals[0].read_text())
        for marker in (
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
            "NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT",
        ):
            self.assertIn(marker, body["standing_markers"])

    def test_11_invariant_constants(self):
        self.assertIs(self.script.LIVE_TRADING_UNSUPPORTED, True)
        self.assertIs(self.script.NO_ORDER_PLACEMENT, True)
        self.assertIs(self.script.NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT, True)
        self.assertIs(self.script.EDGE_GATE_ENABLED, False)
        self.assertIs(self.script.ALLOW_BROKER_PAPER, False)

    def test_12_apply_without_operator_confirmed_refuses(self):
        """--apply alone (without --operator-confirmed) is a no-op refusal."""
        self._write_safe_mode_entered(_now() - timedelta(hours=2))
        self._write_broker_repair_entry("AVAX/USD")
        self._write_marker("AVAX/USD", _now())
        self._write_equity_gap("EQUITY_GAP_OK")
        # --apply alone — should refuse.
        rc = self.script.main(["--dry-run", "false", "--apply"])
        self.assertEqual(rc, 0)
        proposals = list(self._markers_dir.glob(
            "safe_mode_reconciliation_proposal_*.json"))
        self.assertEqual(proposals, [],
                         "--apply without --operator-confirmed must NOT write")


if __name__ == "__main__":
    unittest.main()
