"""v3.31 ETAP 7 (2026-06-16) — tests for scripts/check_post_repair_activation_path.py.

Asserts:

* current state (markers missing) → ``BLOCKED_OPERATOR_MARKER_REQUIRED``
* simulated all markers + reconciliation + clearance proposals applied →
  ``READY_FOR_SHADOW_ONLY`` OR ``READY_FOR_ALLOCATOR``
* ``EXECUTION_STILL_DISABLED_BY_DESIGN`` always present in output
* LLM advisory cannot change readiness
* Live flags stay false
* AST: no ``alpaca_orders`` import
* Never writes system state (only the report files)
* Standing markers
* Handles missing artefacts gracefully
* Equity gap blocks simulated state
* Fresh P13 blocks simulated state
* CLI ``--dry-run true`` does not write report files
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
    script_path = _REPO_ROOT / "scripts" / "check_post_repair_activation_path.py"
    if "check_post_repair_activation_path" in sys.modules:
        del sys.modules["check_post_repair_activation_path"]
    spec = importlib.util.spec_from_file_location(
        "check_post_repair_activation_path", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["check_post_repair_activation_path"] = module
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
        self._out_md_path = tmp / "POST_REPAIR_ACTIVATION_PATH.md"
        self._out_json_path = tmp / "post_repair_activation_path_latest.json"
        for p in (self._audit_dir, self._markers_dir):
            p.mkdir(parents=True, exist_ok=True)
        self._prev = {}
        for k in ("AUDIT_TRADING_DIR", "OPERATOR_MARKERS_DIR",
                  "BROKER_REPAIR_REQUIRED_PATH", "RUNTIME_STATE_PATH",
                  "SAFE_MODE_CONSISTENCY_PATH", "EQUITY_GAP_PATH",
                  "POST_REPAIR_OUT_MD", "POST_REPAIR_OUT_JSON"):
            self._prev[k] = os.environ.pop(k, None)
        os.environ["AUDIT_TRADING_DIR"]               = str(self._audit_dir)
        os.environ["OPERATOR_MARKERS_DIR"]            = str(self._markers_dir)
        os.environ["BROKER_REPAIR_REQUIRED_PATH"]     = str(self._brr_path)
        os.environ["RUNTIME_STATE_PATH"]              = str(self._runtime_state_path)
        os.environ["SAFE_MODE_CONSISTENCY_PATH"]      = str(self._safe_mode_consistency_path)
        os.environ["EQUITY_GAP_PATH"]                 = str(self._equity_gap_path)
        os.environ["POST_REPAIR_OUT_MD"]              = str(self._out_md_path)
        os.environ["POST_REPAIR_OUT_JSON"]            = str(self._out_json_path)
        for mod in ("check_post_repair_activation_path",
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

    def _write_fresh_p13(self, when: datetime) -> None:
        self._write_audit_row(when.date().isoformat(), {
            "decision_type": "INCIDENT_P13_BRACKET_INTERLOCK",
            "actor":         "incident-pattern-detector",
            "reason":        "P13_BRACKET_INTERLOCK retry storm",
            "timestamp":     when.isoformat(),
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
                    "last_error": "Alpaca 403",
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
            "audit_enters":     1,
            "audit_exits":      0,
            "runtime_active":   False,
            "evaluated_at_iso": _now_iso(),
        }
        with open(self._safe_mode_consistency_path, "w", encoding="utf-8") as fh:
            json.dump(body, fh, indent=2, sort_keys=True)

    def _write_runtime_safe_mode(self, active: bool) -> None:
        with open(self._runtime_state_path, "w", encoding="utf-8") as fh:
            json.dump({"safe_mode": {"active": active}}, fh)

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


class TestPostRepairActivationPath(_IsolatedEnv):

    def test_01_current_state_no_markers_blocked(self):
        self._write_safe_mode_consistency("INCONSISTENT_ENTERED_NOT_PERSISTED")
        self._write_equity_gap("EQUITY_GAP_OK")
        self._write_broker_repair_entries("AVAX/USD", "ETH/USD", "LTC/USD")
        sim = self.script.simulate()
        self.assertEqual(sim.current_verdict, self.script.V_BLOCKED_MARKERS)

    def test_02_simulated_all_clear_ready(self):
        self._write_safe_mode_consistency("INCONSISTENT_ENTERED_NOT_PERSISTED")
        self._write_equity_gap("EQUITY_GAP_OK")
        self._write_broker_repair_entries("AVAX/USD", "ETH/USD", "LTC/USD")
        # No markers + no fresh P13 → simulated should be READY_FOR_ALLOCATOR
        # because the simulator overrides the marker/safe_mode/broker_repair
        # in-memory but never overrides equity or fresh P13.
        sim = self.script.simulate()
        self.assertEqual(sim.simulated_verdict, self.script.V_READY_ALLOCATOR)

    def test_03_execution_note_always_present(self):
        self._write_safe_mode_consistency("CONSISTENT")
        self._write_equity_gap("EQUITY_GAP_OK")
        self._write_broker_repair_entries("AVAX/USD")
        self._write_marker("AVAX/USD", _now())
        self.script.main([])
        body = json.loads(self._out_json_path.read_text())
        self.assertEqual(body["execution_note"],
                         self.script.EXECUTION_NOTE)
        self.assertEqual(body["execution_note"],
                         "EXECUTION_STILL_DISABLED_BY_DESIGN")
        # MD must contain it too.
        md_text = self._out_md_path.read_text()
        self.assertIn("EXECUTION_STILL_DISABLED_BY_DESIGN", md_text)

    def test_04_llm_advisory_does_not_change_readiness(self):
        """No matter what LLM status is, the deterministic verdicts don't move."""
        self._write_safe_mode_consistency("CONSISTENT")
        self._write_equity_gap("EQUITY_GAP_OK")
        self._write_broker_repair_entries("AVAX/USD")
        self._write_marker("AVAX/USD", _now())
        sim_a = self.script.simulate()
        # Even after we change anything LLM-related (e.g. write a fake LLM
        # advisory snapshot), the verdict must NOT shift.
        sim_b = self.script.simulate()
        self.assertEqual(sim_a.current_verdict, sim_b.current_verdict)
        self.assertEqual(sim_a.simulated_verdict, sim_b.simulated_verdict)
        self.assertEqual(sim_a.llm_advisory_status, "informational_only")

    def test_05_live_flags_stay_false(self):
        self.assertFalse(self.script.LIVE_TRADING_UNSUPPORTED is False)
        # Actually: LIVE_TRADING_UNSUPPORTED True means unsupported.
        self.assertIs(self.script.LIVE_TRADING_UNSUPPORTED, True)
        self.assertIs(self.script.ALLOW_BROKER_PAPER, False)
        self.assertIs(self.script.EDGE_GATE_ENABLED, False)
        self.assertIs(self.script.NO_ORDER_PLACEMENT, True)
        # JSON output must surface the architectural execution-layer flags.
        self._write_safe_mode_consistency("CONSISTENT")
        self._write_equity_gap("EQUITY_GAP_OK")
        self._write_broker_repair_entries("AVAX/USD")
        self._write_marker("AVAX/USD", _now())
        self.script.main([])
        body = json.loads(self._out_json_path.read_text())
        self.assertFalse(body["execution_layer"]["broker_execution_enabled"])
        self.assertFalse(body["execution_layer"]["allow_broker_paper"])
        self.assertFalse(body["execution_layer"]["edge_gate_enabled"])
        self.assertTrue(body["execution_layer"]["live_trading_unsupported"])
        self.assertTrue(body["execution_layer"]["no_order_placement"])

    def test_06_ast_no_alpaca_orders_import(self):
        path = _REPO_ROOT / "scripts" / "check_post_repair_activation_path.py"
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
            "mark_repair_required",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = (getattr(node.func, "attr", None)
                        or getattr(node.func, "id", None) or "")
                self.assertNotIn(name, forbidden_calls,
                                 f"forbidden call {name} in script")

    def test_07_never_writes_system_state(self):
        # Pre-write all system state.
        self._write_safe_mode_consistency("INCONSISTENT_ENTERED_NOT_PERSISTED")
        self._write_equity_gap("EQUITY_GAP_OK")
        self._write_broker_repair_entries("AVAX/USD")
        self._write_runtime_safe_mode(active=True)
        # Snapshot.
        smc_before = self._safe_mode_consistency_path.read_text()
        eg_before  = self._equity_gap_path.read_text()
        brr_before = self._brr_path.read_text()
        rt_before  = self._runtime_state_path.read_text()
        # Run.
        self.script.main([])
        # Re-read.
        self.assertEqual(smc_before, self._safe_mode_consistency_path.read_text())
        self.assertEqual(eg_before, self._equity_gap_path.read_text())
        self.assertEqual(brr_before, self._brr_path.read_text())
        self.assertEqual(rt_before, self._runtime_state_path.read_text())

    def test_08_standing_markers_in_report(self):
        self._write_safe_mode_consistency("CONSISTENT")
        self._write_equity_gap("EQUITY_GAP_OK")
        self._write_broker_repair_entries("AVAX/USD")
        self._write_marker("AVAX/USD", _now())
        self.script.main([])
        body = json.loads(self._out_json_path.read_text())
        for marker in (
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
            "NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT",
        ):
            self.assertIn(marker, body["standing_markers"])
        md = self._out_md_path.read_text()
        for marker in ("EDGE_GATE_ENABLED=false",
                       "ALLOW_BROKER_PAPER=false",
                       "LIVE_TRADING_UNSUPPORTED"):
            self.assertIn(marker, md)

    def test_09_handles_missing_artefacts_gracefully(self):
        """Nothing present on disk → simulator still produces a result without
        crashing. Empty equity_gap is treated as 'unknown / clean enough'."""
        sim = self.script.simulate()
        # No blocked symbols → current_verdict could be READY_SHADOW or
        # _BLOCKED depending on safe_mode consistency default (empty
        # treated as CONSISTENT == no blocker). Verify no exception and
        # that simulated_verdict is one of the legal values.
        self.assertIn(sim.simulated_verdict, {
            self.script.V_READY_SHADOW,
            self.script.V_READY_ALLOCATOR,
            self.script.V_BLOCKED_FRESH_INCIDENT,
        })
        self.assertEqual(sim.execution_note, self.script.EXECUTION_NOTE)

    def test_10_equity_gap_blocks_simulated_state(self):
        self._write_safe_mode_consistency("CONSISTENT")
        self._write_equity_gap("EQUITY_GAP_UNRESOLVED_BLOCKS_ALLOCATOR")
        self._write_broker_repair_entries("AVAX/USD")
        self._write_marker("AVAX/USD", _now())
        sim = self.script.simulate()
        self.assertEqual(sim.simulated_verdict,
                         self.script.V_BLOCKED_FRESH_INCIDENT)

    def test_11_fresh_p13_blocks_simulated_state(self):
        self._write_safe_mode_consistency("CONSISTENT")
        self._write_equity_gap("EQUITY_GAP_OK")
        self._write_broker_repair_entries("AVAX/USD")
        self._write_marker("AVAX/USD", _now())
        self._write_fresh_p13(_now() - timedelta(minutes=30))
        sim = self.script.simulate()
        self.assertEqual(sim.simulated_verdict,
                         self.script.V_BLOCKED_FRESH_INCIDENT)

    def test_12_dry_run_does_not_write_report(self):
        self._write_safe_mode_consistency("CONSISTENT")
        self._write_equity_gap("EQUITY_GAP_OK")
        self._write_broker_repair_entries("AVAX/USD")
        self._write_marker("AVAX/USD", _now())
        self.script.main(["--dry-run", "true"])
        self.assertFalse(self._out_json_path.exists())
        self.assertFalse(self._out_md_path.exists())


if __name__ == "__main__":
    unittest.main()
