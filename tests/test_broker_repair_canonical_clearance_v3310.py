"""v3.31 ETAP 4 (2026-06-16) — tests for scripts/propose_clear_broker_repair_canonical.py.

Asserts:

* ``AVAX/USD`` with marker BEFORE last failure → ``CLEARANCE_BLOCKED_MARKER_BEFORE_LAST_FAILURE``
* ``AVAX/USD`` with marker AFTER last failure + fresh failure → ``CLEARANCE_BLOCKED_FRESH_FAILURE``
* ``AVAX/USD`` all clear + safe_mode still inconsistent → ``CLEARANCE_BLOCKED_SAFE_MODE``
* ``AVAX/USD`` all clear → ``CLEARANCE_READY``
* All 3 canonical symbols ready + ``--apply --operator-confirmed`` → proposal written
* Alias entries already normalized post-v3.30 (no AVAX/AVAXUSD duplicates)
* Never auto-clears ``broker_repair_required`` (verifies no state mutation)
* AST: no ``alpaca_orders`` import
* Standing markers footer
* Equity gap blocks
* ``--apply`` alone without ``--operator-confirmed`` refuses
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
    script_path = _REPO_ROOT / "scripts" / "propose_clear_broker_repair_canonical.py"
    if "propose_clear_broker_repair_canonical" in sys.modules:
        del sys.modules["propose_clear_broker_repair_canonical"]
    spec = importlib.util.spec_from_file_location(
        "propose_clear_broker_repair_canonical", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["propose_clear_broker_repair_canonical"] = module
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
        self._safe_mode_consistency_path = tmp / "safe_mode_consistency_latest.json"
        self._equity_gap_path = tmp / "equity_gap_reconciliation_latest.json"
        for p in (self._audit_dir, self._markers_dir):
            p.mkdir(parents=True, exist_ok=True)
        self._prev = {}
        for k in ("AUDIT_TRADING_DIR", "OPERATOR_MARKERS_DIR",
                  "BROKER_REPAIR_REQUIRED_PATH", "RUNTIME_STATE_PATH",
                  "SAFE_MODE_CONSISTENCY_PATH", "EQUITY_GAP_PATH"):
            self._prev[k] = os.environ.pop(k, None)
        os.environ["AUDIT_TRADING_DIR"]               = str(self._audit_dir)
        os.environ["OPERATOR_MARKERS_DIR"]            = str(self._markers_dir)
        os.environ["BROKER_REPAIR_REQUIRED_PATH"]     = str(self._brr_path)
        os.environ["RUNTIME_STATE_PATH"]              = str(self._runtime_state_path)
        os.environ["SAFE_MODE_CONSISTENCY_PATH"]      = str(self._safe_mode_consistency_path)
        os.environ["EQUITY_GAP_PATH"]                 = str(self._equity_gap_path)
        for mod in ("propose_clear_broker_repair_canonical",
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

    def _write_alpaca_403(self, when: datetime, symbol: str) -> None:
        self._write_audit_row(when.date().isoformat(), {
            "decision_type":   "CLOSE_POSITION",
            "decision":        "FAILED",
            "actor":           "safe_close",
            "affected_symbols": [symbol],
            "reason":          "Alpaca 403 insufficient balance",
            "errors":          ["Alpaca 403 insufficient balance"],
            "status":          "failed",
            "timestamp":       when.isoformat(),
        })

    def _write_broker_repair_entries(self, *symbols: str) -> None:
        body = {
            "schema_version": "v3.28",
            "updated_at": _now_iso(),
            "entries": {
                sym: {
                    "symbol": sym,
                    "incident_type": "P13_BRACKET_INTERLOCK",
                    "first_seen_iso": _now_iso(),
                    "last_seen_iso":  _now_iso(),
                    "failed_attempts": 2,
                    "last_error": "Alpaca 403 insufficient balance",
                    "manual_action_required": "operator review",
                    "allowed_next_actions": ["operator_marker_required"],
                    "safe_mode_reason": "P13_BRACKET_INTERLOCK",
                    "retry_after_iso": None,
                    "broker_calls_blocked_until_iso": None,
                } for sym in symbols
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

    def _write_safe_mode_consistency(self, verdict: str) -> None:
        body = {
            "schema_version":   "v3.29",
            "verdict":          verdict,
            "blocker":          ("BLOCK_SAFE_MODE_INCONSISTENT"
                                 if verdict != "CONSISTENT" else None),
            "detail":           "test",
            "audit_events":     1,
            "audit_enters":     1,
            "audit_exits":      0,
            "runtime_active":   False,
            "evaluated_at_iso": _now_iso(),
        }
        with open(self._safe_mode_consistency_path, "w", encoding="utf-8") as fh:
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


class TestBrokerRepairCanonicalClearance(_IsolatedEnv):

    def test_01_marker_before_last_failure_blocks(self):
        # Last failure NOW (recent), marker recorded 24h ago.
        self._write_safe_mode_consistency("CONSISTENT")
        self._write_equity_gap("EQUITY_GAP_OK")
        self._write_broker_repair_entries("AVAX/USD")
        # Marker before failure.
        self._write_marker("AVAX/USD", _now() - timedelta(hours=24))
        # Recent (after-marker) failure.
        self._write_alpaca_403(_now() - timedelta(minutes=120), "AVAX/USD")
        report = self.script._evaluate_all(apply_mode=False)
        avax = next(s for s in report.per_symbol if s["symbol"] == "AVAX/USD")
        # marker_ts < last_failure_ts → MARKER_BEFORE_FAILURE
        # (also: FRESH_FAILURE matches; precedence checks MARKER_BEFORE first.)
        self.assertEqual(avax["verdict"],
                         self.script.V_MARKER_BEFORE_FAILURE)

    def test_02_marker_after_failure_plus_fresh_failure_blocks(self):
        # Failure 24h ago, marker 12h ago, then fresh failure 1h ago.
        self._write_safe_mode_consistency("CONSISTENT")
        self._write_equity_gap("EQUITY_GAP_OK")
        self._write_broker_repair_entries("AVAX/USD")
        self._write_alpaca_403(_now() - timedelta(hours=24), "AVAX/USD")
        self._write_marker("AVAX/USD", _now() - timedelta(hours=12))
        # Fresh failure AFTER marker — but inside RETRY_STORM_WINDOW
        # (60 min) so storm_active fires; either way it's V_FRESH_FAILURE.
        self._write_alpaca_403(_now() - timedelta(minutes=30), "AVAX/USD")
        report = self.script._evaluate_all(apply_mode=False)
        avax = next(s for s in report.per_symbol if s["symbol"] == "AVAX/USD")
        self.assertEqual(avax["verdict"], self.script.V_FRESH_FAILURE)

    def test_03_all_clear_safe_mode_inconsistent_blocks(self):
        # Marker fresh, no recent failure, but safe_mode still INCONSISTENT.
        self._write_safe_mode_consistency("INCONSISTENT_ENTERED_NOT_PERSISTED")
        self._write_equity_gap("EQUITY_GAP_OK")
        self._write_broker_repair_entries("AVAX/USD")
        self._write_marker("AVAX/USD", _now())
        report = self.script._evaluate_all(apply_mode=False)
        avax = next(s for s in report.per_symbol if s["symbol"] == "AVAX/USD")
        self.assertEqual(avax["verdict"], self.script.V_SAFE_MODE)

    def test_04_all_clear_ready(self):
        self._write_safe_mode_consistency("CONSISTENT")
        self._write_equity_gap("EQUITY_GAP_OK")
        self._write_broker_repair_entries("AVAX/USD")
        self._write_marker("AVAX/USD", _now() - timedelta(minutes=5))
        # No audit failures at all.
        report = self.script._evaluate_all(apply_mode=False)
        avax = next(s for s in report.per_symbol if s["symbol"] == "AVAX/USD")
        self.assertEqual(avax["verdict"], self.script.V_READY)

    def test_05_all_three_ready_apply_writes_proposal(self):
        self._write_safe_mode_consistency("CONSISTENT")
        self._write_equity_gap("EQUITY_GAP_OK")
        self._write_broker_repair_entries("AVAX/USD", "ETH/USD", "LTC/USD")
        for sym in ("AVAX/USD", "ETH/USD", "LTC/USD"):
            self._write_marker(sym, _now() - timedelta(minutes=5))
        rc = self.script.main(["--dry-run", "false",
                               "--apply", "--operator-confirmed"])
        self.assertEqual(rc, 0)
        proposals = list(self._markers_dir.glob(
            "broker_repair_clearance_proposal_*.json"))
        self.assertEqual(len(proposals), 1)
        body = json.loads(proposals[0].read_text())
        self.assertIn("per_symbol", body)
        self.assertEqual(len(body["per_symbol"]), 3)
        for s in body["per_symbol"]:
            self.assertEqual(s["verdict"], self.script.V_READY)
        # Every action must reference Operator and clear_repair.
        for action in body["proposed_actions"]:
            self.assertIn("Operator:", action)
            self.assertIn("clear_repair", action)

    def test_06_no_alias_duplicates_after_v3_30(self):
        """v3.30 normalization means only canonical entries exist; the
        evaluator must not double-count an alias as a separate symbol."""
        self._write_safe_mode_consistency("CONSISTENT")
        self._write_equity_gap("EQUITY_GAP_OK")
        # Only the canonical key — no AVAX or AVAXUSD raw alias.
        self._write_broker_repair_entries("AVAX/USD")
        report = self.script._evaluate_all(apply_mode=False)
        self.assertEqual(report.blocked_symbols, ["AVAX/USD"])
        self.assertNotIn("AVAX", report.blocked_symbols)
        self.assertNotIn("AVAXUSD", report.blocked_symbols)

    def test_07_never_auto_clears(self):
        """Even when all preconditions hold, writing the proposal must
        NOT mutate broker_repair_required."""
        self._write_safe_mode_consistency("CONSISTENT")
        self._write_equity_gap("EQUITY_GAP_OK")
        self._write_broker_repair_entries("AVAX/USD")
        self._write_marker("AVAX/USD", _now())
        brr_before = self._brr_path.read_text()
        self.script.main(["--dry-run", "false",
                          "--apply", "--operator-confirmed"])
        brr_after = self._brr_path.read_text()
        self.assertEqual(brr_before, brr_after,
                         "writing proposal must NOT mutate broker_repair_required")

    def test_08_ast_no_alpaca_orders_import(self):
        path = _REPO_ROOT / "scripts" / "propose_clear_broker_repair_canonical.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden = {"alpaca_orders", "shared.alpaca_orders"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertNotIn(n.name, forbidden)
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, forbidden)
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

    def test_09_standing_markers_in_proposal(self):
        self._write_safe_mode_consistency("CONSISTENT")
        self._write_equity_gap("EQUITY_GAP_OK")
        self._write_broker_repair_entries("AVAX/USD")
        self._write_marker("AVAX/USD", _now())
        self.script.main(["--dry-run", "false",
                          "--apply", "--operator-confirmed"])
        proposals = list(self._markers_dir.glob(
            "broker_repair_clearance_proposal_*.json"))
        body = json.loads(proposals[0].read_text())
        for marker in (
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
            "NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT",
        ):
            self.assertIn(marker, body["standing_markers"])

    def test_10_equity_gap_blocks(self):
        self._write_safe_mode_consistency("CONSISTENT")
        self._write_equity_gap("EQUITY_GAP_UNRESOLVED_BLOCKS_ALLOCATOR")
        self._write_broker_repair_entries("AVAX/USD")
        self._write_marker("AVAX/USD", _now())
        report = self.script._evaluate_all(apply_mode=False)
        avax = next(s for s in report.per_symbol if s["symbol"] == "AVAX/USD")
        self.assertEqual(avax["verdict"], self.script.V_EQUITY_GAP)

    def test_11_apply_without_operator_confirmed_refuses(self):
        self._write_safe_mode_consistency("CONSISTENT")
        self._write_equity_gap("EQUITY_GAP_OK")
        self._write_broker_repair_entries("AVAX/USD")
        self._write_marker("AVAX/USD", _now())
        rc = self.script.main(["--dry-run", "false", "--apply"])
        self.assertEqual(rc, 0)
        proposals = list(self._markers_dir.glob(
            "broker_repair_clearance_proposal_*.json"))
        self.assertEqual(proposals, [],
                         "--apply without --operator-confirmed must NOT write")

    def test_12_invariant_constants(self):
        self.assertIs(self.script.LIVE_TRADING_UNSUPPORTED, True)
        self.assertIs(self.script.NO_ORDER_PLACEMENT, True)
        self.assertIs(self.script.NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT, True)
        self.assertIs(self.script.EDGE_GATE_ENABLED, False)
        self.assertIs(self.script.ALLOW_BROKER_PAPER, False)


if __name__ == "__main__":
    unittest.main()
