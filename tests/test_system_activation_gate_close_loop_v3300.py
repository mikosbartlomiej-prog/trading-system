"""v3.30 ETAP 6 (2026-06-16) — tests for shared/system_activation_gate.py
close-loop integration.

Asserts:

* canonical normalization respected — broker_repair entry written as
  any of {``AVAX``, ``AVAXUSD``, ``AVAX/USD``} still blocks the
  canonical ``AVAX/USD``;
* operator marker without fresh P13 + quiet broker → shadow allowed
  while allocator still BLOCKS on the deterministic verdict;
* operator marker WITH fresh P13 → shadow NOT allowed;
* LLM advisory irrelevant to the decision (and to shadow_only_allowed);
* all 9 verdict branches reachable;
* default fail-CLOSED on any check raising;
* shadow_only_allowed independent of LLM availability;
* no broker call (AST guard);
* standing markers preserved;
* audit row written;
* AST: no ``alpaca_orders`` import in the module.
"""

from __future__ import annotations

import ast
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
    for name in (
        "system_activation_gate",
        "safe_mode",
        "runtime_state",
        "broker_repair_required",
        "operator_repair_state",
        "symbol_normalization",
    ):
        if name in sys.modules:
            del sys.modules[name]
    import system_activation_gate as g  # noqa
    return g


class _CloseLoopEnv(unittest.TestCase):
    """Per-test tmp dir for state, audit, and operator markers."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_root = Path(self._tmp.name)
        (self._tmp_root / "learning-loop").mkdir(parents=True, exist_ok=True)
        (self._tmp_root / "config").mkdir(parents=True, exist_ok=True)
        (self._tmp_root / "journal" / "autonomy").mkdir(parents=True, exist_ok=True)

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
        self._orig_root = self.gate.REPO_ROOT
        self.gate.REPO_ROOT = self._tmp_root
        self.gate._REPO_ROOT = self._tmp_root

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

    def _write_broker_repair(self, entries: dict) -> None:
        p = self._tmp_root / "learning-loop" / "broker_repair_required_latest.json"
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({
                "schema_version": "v3.28",
                "updated_at": _iso(_now()),
                "entries": entries,
            }, fh)

    def _make_entry(self, symbol: str) -> dict:
        return {
            "symbol":          symbol,
            "incident_type":   "P13",
            "first_seen_iso":  _iso(_now()),
            "last_seen_iso":   _iso(_now()),
            "failed_attempts": 1,
            "last_error":      "x",
            "manual_action_required": "x",
            "allowed_next_actions":  ["operator_marker_required"],
            "safe_mode_reason":      "x",
            "broker_calls_blocked_until_iso": None,
            "retry_after_iso": None,
        }

    def _write_equity_gap_ok(self) -> None:
        p = self._tmp_root / "learning-loop" / "equity_gap_reconciliation_latest.json"
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({
                "schema_version": "v3.29",
                "verdict": "EQUITY_GAP_OK",
                "block_allocator": False,
                "generated_at_iso": _iso(_now()),
                "confidence": "MEDIUM",
                "components": {},
                "evidence": {},
            }, fh)

    def _write_operator_marker(self, symbol: str) -> None:
        d = self._tmp_root / "operator_markers"
        d.mkdir(parents=True, exist_ok=True)
        safe = symbol.replace("/", "_").replace(" ", "_")
        date_iso = _now().date().isoformat()
        p = d / f"{safe}_{date_iso}.json"
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({
                "symbol": symbol,
                "incident_type": "P13",
                "dashboard_checked": True,
                "open_orders_checked": True,
                "stale_oco_cancelled_by_operator": "true",
                "position_closed_by_operator": "true",
                "final_position_state": "flat",
                "final_open_orders_state": "none",
                "equity_checked": True,
                "operator_note": "ok",
                "timestamp_iso": _iso(_now()),
                "source": "OPERATOR_MANUAL_CONFIRMATION",
                "does_not_execute_orders": True,
            }, fh)

    def _emit_p13_audit_row(self, when: datetime | None = None) -> None:
        when = when or _now()
        d = self._tmp_root / "journal" / "autonomy"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{when.date().isoformat()}.jsonl"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "decision_type": "CLEANUP_STALE_ORDERS",
                "decision":      "DETECTED",
                "actor":         "incident_pattern_detector",
                "reason":        "P13_bracket_interlock_blocked_close: 3 CLOSE_POSITION FAILED",
                "timestamp":     _iso(when),
                "risk_metrics":  {"pattern": "P13_bracket_interlock_blocked_close",
                                   "severity": "CRITICAL"},
            }, sort_keys=True) + "\n")

    def _set_market_hours(self, in_hours: bool) -> None:
        self.gate._is_us_market_hours = lambda now=None: in_hours

    def _set_llm(self, status: str) -> None:
        self.gate._read_llm_status = lambda: status


# ── 1. Canonical normalization ────────────────────────────────────────────────

class TestCanonicalNormalization(_CloseLoopEnv):

    def test_01_bare_base_alias_resolves_to_canonical(self):
        self._write_broker_repair({"AVAX": self._make_entry("AVAX")})
        self._write_equity_gap_ok()
        self._set_market_hours(False)
        result = self.gate.evaluate()
        # The bare-base form should canonicalize to AVAX/USD and BLOCK.
        self.assertIn(
            result.decision,
            {self.gate.SystemActivationDecision.ALLOCATOR_BLOCKED_BROKER_REPAIR,
             self.gate.SystemActivationDecision.ALLOCATOR_BLOCKED_OPERATOR_CONFIRMATION_REQUIRED},
        )

    def test_02_baseusd_alias_resolves_to_canonical(self):
        self._write_broker_repair({"AVAXUSD": self._make_entry("AVAXUSD")})
        self._write_equity_gap_ok()
        self._set_market_hours(False)
        result = self.gate.evaluate()
        self.assertIn(
            result.decision,
            {self.gate.SystemActivationDecision.ALLOCATOR_BLOCKED_BROKER_REPAIR,
             self.gate.SystemActivationDecision.ALLOCATOR_BLOCKED_OPERATOR_CONFIRMATION_REQUIRED},
        )

    def test_03_slash_form_already_canonical(self):
        self._write_broker_repair({"AVAX/USD": self._make_entry("AVAX/USD")})
        self._write_equity_gap_ok()
        self._set_market_hours(False)
        result = self.gate.evaluate()
        self.assertIn(
            result.decision,
            {self.gate.SystemActivationDecision.ALLOCATOR_BLOCKED_BROKER_REPAIR,
             self.gate.SystemActivationDecision.ALLOCATOR_BLOCKED_OPERATOR_CONFIRMATION_REQUIRED},
        )


# ── 2. Operator confirmation interaction with P13 freshness ──────────────────

class TestOperatorMarkerWithP13(_CloseLoopEnv):

    def test_04_marker_without_fresh_p13_quiet_broker_shadow_allowed(self):
        # Quarantine present, marker present, no fresh P13 audit row.
        # Verdict still BLOCKS (operator must finalise via clear_repair)
        # but shadow simulation should be PERMITTED because the broker
        # is quiet.
        self._write_broker_repair({"AVAX/USD": self._make_entry("AVAX/USD")})
        self._write_operator_marker("AVAX/USD")
        self._write_equity_gap_ok()
        self._set_market_hours(False)
        result = self.gate.evaluate()
        self.assertEqual(
            result.decision,
            self.gate.SystemActivationDecision.ALLOCATOR_BLOCKED_BROKER_REPAIR,
        )
        # No P13 audit emitted → quiet broker → shadow allowed.
        self.assertTrue(result.shadow_only_allowed)

    def test_05_marker_with_fresh_p13_shadow_not_allowed(self):
        self._write_broker_repair({"AVAX/USD": self._make_entry("AVAX/USD")})
        self._write_operator_marker("AVAX/USD")
        self._write_equity_gap_ok()
        self._set_market_hours(False)
        self._emit_p13_audit_row()
        result = self.gate.evaluate()
        # Still BLOCKED on broker_repair AND shadow refused because of
        # the fresh P13 in the audit window.
        self.assertEqual(
            result.decision,
            self.gate.SystemActivationDecision.ALLOCATOR_BLOCKED_BROKER_REPAIR,
        )
        self.assertFalse(result.shadow_only_allowed)


# ── 3. LLM advisory irrelevance ──────────────────────────────────────────────

class TestLLMAdvisoryIrrelevant(_CloseLoopEnv):

    def test_06_llm_unavailable_does_not_change_decision(self):
        self._write_equity_gap_ok()
        self._set_market_hours(False)
        self._set_llm("unavailable")
        result = self.gate.evaluate()
        self.assertEqual(
            result.decision,
            self.gate.SystemActivationDecision.ALLOCATOR_ALLOWED,
        )
        self.assertEqual(result.llm_status, "unavailable")
        self.assertTrue(result.shadow_only_allowed)

    def test_07_llm_advisory_on_does_not_unblock(self):
        # Quarantined symbol → BLOCKED regardless of LLM mood.
        self._write_broker_repair({"AVAX/USD": self._make_entry("AVAX/USD")})
        self._write_equity_gap_ok()
        self._set_market_hours(False)
        self._set_llm("advisory_on")
        result = self.gate.evaluate()
        self.assertEqual(
            result.decision,
            self.gate.SystemActivationDecision.ALLOCATOR_BLOCKED_OPERATOR_CONFIRMATION_REQUIRED,
        )

    def test_08_shadow_only_allowed_independent_of_llm(self):
        # safe_mode active blocks. LLM available → still blocked +
        # shadow flag unaffected by LLM status.
        self._write_runtime({
            "safe_mode": {"active": True, "reason": "test", "trigger": "OPERATOR",
                           "entered_at": _iso(_now()), "forced": True}
        })
        self._write_equity_gap_ok()
        self._set_market_hours(False)
        self._set_llm("advisory_on")
        r_with_llm = self.gate.evaluate()

        # Now drop LLM and re-evaluate.
        self._set_llm("unavailable")
        r_no_llm = self.gate.evaluate()

        self.assertEqual(r_with_llm.decision, r_no_llm.decision)
        self.assertEqual(r_with_llm.shadow_only_allowed, r_no_llm.shadow_only_allowed)


# ── 4. All 9 decision branches reachable ─────────────────────────────────────

class TestAllDecisionBranches(_CloseLoopEnv):

    def test_09_all_nine_branches_reachable(self):
        seen: set[str] = set()

        # Capture the gate's original safe_mode reader so we can
        # restore the real (runtime_state-reading) behaviour between
        # branches.
        original_read_safe_mode = self.gate._read_safe_mode

        # 1. UNKNOWN_BLOCK_FAIL_CLOSED — safe_mode read failure.
        self.gate._read_safe_mode = lambda: (None, "")
        self._write_equity_gap_ok()
        self._set_market_hours(False)
        seen.add(self.gate.evaluate().decision.value)
        # Restore the real reader so subsequent branches actually
        # observe the runtime_state we write below.
        self.gate._read_safe_mode = original_read_safe_mode

        # 2. ALLOCATOR_BLOCKED_SAFE_MODE_INCONSISTENT.
        p = self._tmp_root / "learning-loop" / "safe_mode_consistency_latest.json"
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"verdict": "INCONSISTENT_ENTERED_NOT_PERSISTED"}, fh)
        seen.add(self.gate.evaluate().decision.value)
        p.unlink()

        # 3. ALLOCATOR_BLOCKED_SAFE_MODE.
        self._write_runtime({
            "safe_mode": {"active": True, "reason": "rx", "trigger": "OPERATOR",
                           "entered_at": _iso(_now()), "forced": True}
        })
        seen.add(self.gate.evaluate().decision.value)
        self._write_runtime({})

        # 4. ALLOCATOR_BLOCKED_OPERATOR_CONFIRMATION_REQUIRED.
        self._write_broker_repair({"ETH/USD": self._make_entry("ETH/USD")})
        seen.add(self.gate.evaluate().decision.value)

        # 5. ALLOCATOR_BLOCKED_BROKER_REPAIR (marker present).
        self._write_operator_marker("ETH/USD")
        seen.add(self.gate.evaluate().decision.value)
        # Clear quarantine.
        self._write_broker_repair({})

        # 6. ALLOCATOR_BLOCKED_EQUITY_GAP — schema-invalid.
        p2 = self._tmp_root / "learning-loop" / "equity_gap_reconciliation_latest.json"
        with open(p2, "w", encoding="utf-8") as fh:
            json.dump({"block_allocator": False}, fh)
        seen.add(self.gate.evaluate().decision.value)
        self._write_equity_gap_ok()

        # 7. ALLOCATOR_BLOCKED_POSITION_RECONCILIATION.
        self._set_market_hours(True)
        recon = self._tmp_root / "learning-loop" / "position_reconciliation_latest.json"
        with open(recon, "w", encoding="utf-8") as fh:
            json.dump({"reconciled_at": _iso(_now() - timedelta(hours=4))}, fh)
        seen.add(self.gate.evaluate().decision.value)
        self._set_market_hours(False)
        recon.unlink()

        # 8. ALLOCATOR_BLOCKED_KILL_SWITCH.
        ks = self._tmp_root / "config" / "aggressive_profile.json"
        with open(ks, "w", encoding="utf-8") as fh:
            json.dump({"kill_switch_armed": True}, fh)
        seen.add(self.gate.evaluate().decision.value)
        ks.unlink()

        # 9. ALLOCATOR_ALLOWED — clean state.
        seen.add(self.gate.evaluate().decision.value)

        expected = {
            "UNKNOWN_BLOCK_FAIL_CLOSED",
            "ALLOCATOR_BLOCKED_SAFE_MODE_INCONSISTENT",
            "ALLOCATOR_BLOCKED_SAFE_MODE",
            "ALLOCATOR_BLOCKED_OPERATOR_CONFIRMATION_REQUIRED",
            "ALLOCATOR_BLOCKED_BROKER_REPAIR",
            "ALLOCATOR_BLOCKED_EQUITY_GAP",
            "ALLOCATOR_BLOCKED_POSITION_RECONCILIATION",
            "ALLOCATOR_BLOCKED_KILL_SWITCH",
            "ALLOCATOR_ALLOWED",
        }
        self.assertEqual(seen, expected)


# ── 5. Default fail-CLOSED ───────────────────────────────────────────────────

class TestDefaultFailClosed(_CloseLoopEnv):

    def test_10_default_unknown_on_internal_exception(self):
        # Force any check helper to raise → gate falls through to
        # UNKNOWN_BLOCK_FAIL_CLOSED.
        def _explode():
            raise RuntimeError("boom")
        self.gate._make_snapshot = _explode
        result = self.gate.evaluate()
        self.assertEqual(
            result.decision,
            self.gate.SystemActivationDecision.UNKNOWN_BLOCK_FAIL_CLOSED,
        )
        # shadow_only_allowed must NOT be True when the gate doesn't
        # know the broker state.
        self.assertFalse(result.shadow_only_allowed)


# ── 6. Standing markers + audit ──────────────────────────────────────────────

class TestStandingMarkersAndAudit(_CloseLoopEnv):

    def test_11_standing_markers_preserved(self):
        self._write_equity_gap_ok()
        self._set_market_hours(False)
        result = self.gate.evaluate()
        for marker in self.gate.STANDING_MARKERS:
            self.assertIn(marker, result.standing_markers)
        # All five core markers present.
        self.assertIn("EDGE_GATE_ENABLED=false", result.standing_markers)
        self.assertIn("ALLOW_BROKER_PAPER=false", result.standing_markers)
        self.assertIn("LIVE_TRADING_UNSUPPORTED", result.standing_markers)
        self.assertIn("NO_ORDER_PLACEMENT", result.standing_markers)

    def test_12_audit_row_written_with_shadow_flag(self):
        self._write_equity_gap_ok()
        self._set_market_hours(False)
        result = self.gate.evaluate()
        path = self.gate.write_audit_decision(result)
        self.assertTrue(path.exists())
        line = path.read_text(encoding="utf-8").strip().splitlines()[-1]
        row = json.loads(line)
        self.assertEqual(row["decision_type"], "SYSTEM_ACTIVATION_GATE_DECISION")
        # v3.30 — audit row carries shadow_only_allowed.
        self.assertIn("shadow_only_allowed", row)
        self.assertIsInstance(row["shadow_only_allowed"], bool)


# ── 7. AST no broker imports ─────────────────────────────────────────────────

class TestAstNoBroker(unittest.TestCase):

    def test_13_ast_no_alpaca_imports_or_calls(self):
        src = (_REPO_ROOT / "shared" / "system_activation_gate.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn(a.name, {"alpaca_orders", "shared.alpaca_orders"})
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, {"alpaca_orders", "shared.alpaca_orders"})
            elif isinstance(node, ast.Call):
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
