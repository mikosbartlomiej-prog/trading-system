"""v3.29 ETAP 5 (2026-06-16) — tests for shared/system_activation_gate.py.

Asserts:

* default UNKNOWN_BLOCK_FAIL_CLOSED on internal error,
* safe_mode active blocks,
* safe_mode inconsistent blocks,
* broker repair blocks (no operator confirmations),
* operator confirmation required blocks (operator marker present clears it),
* equity gap unresolved blocks,
* equity schema invalid blocks,
* equity stale blocks,
* position recon stale blocks during market hours,
* kill switch blocks,
* ALLOCATOR_ALLOWED only when all gates clear,
* LLM unavailable does NOT block,
* LLM available does NOT override existing blockers,
* audit row written,
* no broker call (AST guard).
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime) -> str:
    return ts.isoformat()


def _import_gate():
    """Force a fresh import after env tweaks redirect the repo-root paths."""
    for name in (
        "system_activation_gate",
        "safe_mode",
        "runtime_state",
        "broker_repair_required",
        "operator_repair_state",
    ):
        if name in sys.modules:
            del sys.modules[name]
    import system_activation_gate as g  # noqa
    return g


class _IsolatedEnv(unittest.TestCase):
    """Re-roots every state file under a per-test tmp dir.

    We do this by monkey-patching the loader helpers in
    ``system_activation_gate`` to look under ``self._tmp_root`` instead of
    the production repo. That keeps the test 100% deterministic and
    avoids polluting real state files.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_root = Path(self._tmp.name)
        (self._tmp_root / "learning-loop").mkdir(parents=True, exist_ok=True)
        (self._tmp_root / "config").mkdir(parents=True, exist_ok=True)
        (self._tmp_root / "journal" / "autonomy").mkdir(parents=True, exist_ok=True)

        # Audit trail isolated.
        self._prev = {
            "AUDIT_TRADING_DIR": os.environ.pop("AUDIT_TRADING_DIR", None),
            "RUNTIME_STATE_PATH": os.environ.pop("RUNTIME_STATE_PATH", None),
            "OPERATOR_MARKERS_DIR": os.environ.pop("OPERATOR_MARKERS_DIR", None),
            "BROKER_REPAIR_REQUIRED_PATH": os.environ.pop("BROKER_REPAIR_REQUIRED_PATH", None),
            "KILL_SWITCH": os.environ.pop("KILL_SWITCH", None),
        }
        os.environ["AUDIT_TRADING_DIR"] = str(self._tmp_root / "journal" / "autonomy")
        os.environ["RUNTIME_STATE_PATH"] = str(self._tmp_root / "learning-loop" / "runtime_state.json")
        os.environ["OPERATOR_MARKERS_DIR"] = str(self._tmp_root / "operator_markers")
        os.environ["BROKER_REPAIR_REQUIRED_PATH"] = str(
            self._tmp_root / "learning-loop" / "broker_repair_required_latest.json")

        self.gate = _import_gate()
        # Re-point REPO_ROOT in the loaded module so all loader helpers
        # read from the tmp dir.
        self._orig_root = self.gate.REPO_ROOT
        self.gate.REPO_ROOT = self._tmp_root
        self.gate._REPO_ROOT = self._tmp_root

        # Always-zero runtime_state so safe_mode reads inactive cleanly.
        self._write_runtime({})

    def tearDown(self):
        self.gate.REPO_ROOT = self._orig_root
        self.gate._REPO_ROOT = self._orig_root
        for k, v in self._prev.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        self._tmp.cleanup()

    # ── helpers ─────────────────────────────────────────────────────────

    def _write_runtime(self, payload: dict) -> None:
        p = self._tmp_root / "learning-loop" / "runtime_state.json"
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def _write_consistency(self, payload: dict) -> None:
        p = self._tmp_root / "learning-loop" / "safe_mode_consistency_latest.json"
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def _write_broker_repair(self, entries: dict) -> None:
        p = self._tmp_root / "learning-loop" / "broker_repair_required_latest.json"
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({
                "schema_version": "v3.28",
                "updated_at": _iso(_now()),
                "entries": entries,
            }, fh)

    def _write_equity_gap(self, payload: dict) -> None:
        p = self._tmp_root / "learning-loop" / "equity_gap_reconciliation_latest.json"
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def _write_position_recon(self, ts: datetime | None) -> None:
        p = self._tmp_root / "learning-loop" / "position_reconciliation_latest.json"
        body = {
            "reconciled_at": _iso(ts) if ts else None,
            "ts_iso": _iso(ts) if ts else None,
        }
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(body, fh)

    def _write_kill_switch(self, armed: bool) -> None:
        p = self._tmp_root / "config" / "aggressive_profile.json"
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"kill_switch_armed": armed}, fh)

    def _write_operator_marker(self, symbol: str) -> None:
        d = self._tmp_root / "operator_markers"
        d.mkdir(parents=True, exist_ok=True)
        safe = symbol.replace("/", "_").replace(" ", "_")
        date_iso = _now().date().isoformat()
        p = d / f"{safe}_{date_iso}.json"
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({
                "symbol": symbol,
                "incident_type": "P13_BRACKET_INTERLOCK_BACKFILLED",
                "dashboard_checked": True,
                "open_orders_checked": True,
                "stale_oco_cancelled_by_operator": "true",
                "position_closed_by_operator": "true",
                "final_position_state": "flat",
                "final_open_orders_state": "none",
                "equity_checked": True,
                "operator_note": "operator confirmed",
                "timestamp_iso": _iso(_now()),
                "source": "OPERATOR_MANUAL_CONFIRMATION",
                "does_not_execute_orders": True,
            }, fh)

    def _fresh_equity_payload(self, *, block=False, verdict="EQUITY_GAP_OK") -> dict:
        return {
            "schema_version": "v3.29",
            "verdict":        verdict,
            "block_allocator": block,
            "generated_at_iso": _iso(_now()),
            "confidence": "MEDIUM",
            "components": {},
            "evidence": {},
        }

    def _set_market_hours(self, in_hours: bool) -> None:
        """Monkey-patch ``_is_us_market_hours`` for deterministic tests."""
        self.gate._is_us_market_hours = lambda now=None: in_hours

    def _set_llm(self, status: str) -> None:
        self.gate._read_llm_status = lambda: status


class TestDefaultsAndSafeMode(_IsolatedEnv):

    def test_01_default_unknown_on_safe_mode_read_error(self):
        # Force read_state to raise → snapshot._read_safe_mode returns
        # active=None → UNKNOWN_BLOCK_FAIL_CLOSED.
        def _explode():
            raise RuntimeError("boom")
        self.gate._read_safe_mode = lambda: (None, "")
        self._write_equity_gap(self._fresh_equity_payload())
        self._set_market_hours(False)
        result = self.gate.evaluate()
        self.assertEqual(result.decision, self.gate.SystemActivationDecision.UNKNOWN_BLOCK_FAIL_CLOSED)
        self.assertIn("safe_mode_read_error", result.blockers)

    def test_02_safe_mode_active_blocks(self):
        self._write_runtime({
            "safe_mode": {"active": True, "reason": "test", "trigger": "OPERATOR",
                           "entered_at": _iso(_now()), "forced": True}
        })
        self._write_equity_gap(self._fresh_equity_payload())
        self._set_market_hours(False)
        result = self.gate.evaluate()
        self.assertEqual(result.decision,
                         self.gate.SystemActivationDecision.ALLOCATOR_BLOCKED_SAFE_MODE)
        self.assertIn("safe_mode_active", result.blockers)


class TestConsistencyAndRepair(_IsolatedEnv):

    def test_03_safe_mode_inconsistent_blocks(self):
        self._write_consistency({
            "verdict": "INCONSISTENT_ENTERED_NOT_PERSISTED",
            "detail":  "audit shows ENTER, runtime inactive",
        })
        self._write_equity_gap(self._fresh_equity_payload())
        self._set_market_hours(False)
        result = self.gate.evaluate()
        self.assertEqual(result.decision,
                         self.gate.SystemActivationDecision.ALLOCATOR_BLOCKED_SAFE_MODE_INCONSISTENT)

    def test_04_broker_repair_blocks_when_no_operator_marker(self):
        self._write_broker_repair({
            "AVAXUSD": {
                "symbol": "AVAXUSD",
                "incident_type": "P13",
                "first_seen_iso": _iso(_now()),
                "last_seen_iso":  _iso(_now()),
                "failed_attempts": 1,
                "last_error": "x",
                "manual_action_required": "x",
                "allowed_next_actions": ["operator_marker_required"],
                "safe_mode_reason": "x",
                "broker_calls_blocked_until_iso": None,
                "retry_after_iso": None,
            }
        })
        self._write_equity_gap(self._fresh_equity_payload())
        self._set_market_hours(False)
        result = self.gate.evaluate()
        self.assertEqual(
            result.decision,
            self.gate.SystemActivationDecision.ALLOCATOR_BLOCKED_OPERATOR_CONFIRMATION_REQUIRED)

    def test_05_broker_repair_blocks_even_with_confirmation(self):
        # When all blocked symbols ARE operator-confirmed but the
        # quarantine itself has not yet been cleared, we still BLOCK on
        # ALLOCATOR_BLOCKED_BROKER_REPAIR (the operator must finalise).
        self._write_broker_repair({
            "AVAXUSD": {
                "symbol": "AVAXUSD",
                "incident_type": "P13",
                "first_seen_iso": _iso(_now()),
                "last_seen_iso":  _iso(_now()),
                "failed_attempts": 1,
                "last_error": "x",
                "manual_action_required": "x",
                "allowed_next_actions": ["operator_marker_required"],
                "safe_mode_reason": "x",
                "broker_calls_blocked_until_iso": None,
                "retry_after_iso": None,
            }
        })
        self._write_operator_marker("AVAXUSD")
        self._write_equity_gap(self._fresh_equity_payload())
        self._set_market_hours(False)
        result = self.gate.evaluate()
        self.assertEqual(
            result.decision,
            self.gate.SystemActivationDecision.ALLOCATOR_BLOCKED_BROKER_REPAIR)


class TestEquityGap(_IsolatedEnv):

    def test_06_equity_unresolved_blocks(self):
        self._write_equity_gap({
            "schema_version": "v3.29",
            "verdict": "EQUITY_GAP_UNRESOLVED_BLOCKS_ALLOCATOR",
            "block_allocator": True,
            "generated_at_iso": _iso(_now()),
        })
        self._set_market_hours(False)
        result = self.gate.evaluate()
        self.assertEqual(result.decision,
                         self.gate.SystemActivationDecision.ALLOCATOR_BLOCKED_EQUITY_GAP)

    def test_07_equity_schema_invalid_blocks(self):
        # Missing required key 'verdict'.
        self._write_equity_gap({
            "generated_at_iso": _iso(_now()),
            "block_allocator": False,
        })
        self._set_market_hours(False)
        result = self.gate.evaluate()
        self.assertEqual(result.decision,
                         self.gate.SystemActivationDecision.ALLOCATOR_BLOCKED_EQUITY_GAP)
        self.assertTrue(any("schema_missing_keys" in b for b in result.blockers))

    def test_08_equity_stale_blocks(self):
        old = _now() - timedelta(days=3)
        self._write_equity_gap({
            "schema_version": "v3.29",
            "verdict": "EQUITY_GAP_OK",
            "block_allocator": False,
            "generated_at_iso": _iso(old),
        })
        self._set_market_hours(False)
        result = self.gate.evaluate()
        self.assertEqual(result.decision,
                         self.gate.SystemActivationDecision.ALLOCATOR_BLOCKED_EQUITY_GAP)
        self.assertTrue(any("stale_seconds" in b for b in result.blockers))


class TestRemainingChecks(_IsolatedEnv):

    def test_09_position_recon_stale_blocks_during_market_hours(self):
        self._write_equity_gap(self._fresh_equity_payload())
        self._set_market_hours(True)
        self._write_position_recon(_now() - timedelta(hours=4))
        result = self.gate.evaluate()
        self.assertEqual(
            result.decision,
            self.gate.SystemActivationDecision.ALLOCATOR_BLOCKED_POSITION_RECONCILIATION)

    def test_10_kill_switch_blocks(self):
        self._write_equity_gap(self._fresh_equity_payload())
        self._set_market_hours(False)
        self._write_kill_switch(True)
        # Force fresh kill-switch read inside the gate.
        result = self.gate.evaluate()
        self.assertEqual(result.decision,
                         self.gate.SystemActivationDecision.ALLOCATOR_BLOCKED_KILL_SWITCH)

    def test_11_allocator_allowed_only_when_all_clear(self):
        self._write_equity_gap(self._fresh_equity_payload())
        self._set_market_hours(False)  # avoid recon check
        self._write_kill_switch(False)
        result = self.gate.evaluate()
        self.assertEqual(result.decision,
                         self.gate.SystemActivationDecision.ALLOCATOR_ALLOWED)


class TestLLMIsAdvisoryOnly(_IsolatedEnv):

    def test_12_llm_unavailable_does_not_block(self):
        # Even with LLM unavailable, an otherwise-clean stack returns ALLOWED.
        self._write_equity_gap(self._fresh_equity_payload())
        self._set_market_hours(False)
        self._set_llm("unavailable")
        result = self.gate.evaluate()
        self.assertEqual(result.decision,
                         self.gate.SystemActivationDecision.ALLOCATOR_ALLOWED)
        self.assertEqual(result.llm_status, "unavailable")

    def test_13_llm_available_does_not_override_blockers(self):
        # safe_mode active + LLM "advisory_on" → still BLOCKED.
        self._write_runtime({
            "safe_mode": {"active": True, "reason": "test", "trigger": "OPERATOR",
                           "entered_at": _iso(_now()), "forced": True}
        })
        self._write_equity_gap(self._fresh_equity_payload())
        self._set_market_hours(False)
        self._set_llm("advisory_on")
        result = self.gate.evaluate()
        self.assertEqual(result.decision,
                         self.gate.SystemActivationDecision.ALLOCATOR_BLOCKED_SAFE_MODE)
        self.assertEqual(result.llm_status, "advisory_on")


class TestAuditAndAst(_IsolatedEnv):

    def test_14_audit_row_written(self):
        self._write_equity_gap(self._fresh_equity_payload())
        self._set_market_hours(False)
        result = self.gate.evaluate()
        path = self.gate.write_audit_decision(result)
        self.assertTrue(path.exists())
        line = path.read_text(encoding="utf-8").strip().splitlines()[-1]
        row = json.loads(line)
        self.assertEqual(row["decision_type"], "SYSTEM_ACTIVATION_GATE_DECISION")
        self.assertIn(row["decision"], {d.value for d in self.gate.SystemActivationDecision})
        # Standing markers preserved.
        for marker in self.gate.STANDING_MARKERS:
            self.assertIn(marker, row["standing_markers"])

    def test_15_ast_no_broker_import_or_calls(self):
        src = (_REPO_ROOT / "shared" / "system_activation_gate.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn(a.name, {"alpaca_orders", "shared.alpaca_orders"})
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module,
                                  {"alpaca_orders", "shared.alpaca_orders"})
            elif isinstance(node, ast.Call):
                # Reject any direct call to the forbidden functions.
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
