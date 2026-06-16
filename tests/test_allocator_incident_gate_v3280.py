"""v3.28 ETAP 3+8 (2026-06-16) — tests for shared/allocator_incident_gate.py
and the allocator wiring in scripts/execute_allocation_plan.py.

Asserts the gate defaults to BLOCK_UNKNOWN, only ALLOWs when EVERY
check affirmatively passes, never calls the broker, and is wired into
the morning allocator before any plan execution.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))

import allocator_incident_gate as gate  # noqa: E402
import broker_repair_required as brr  # noqa: E402
import safe_mode as sm  # noqa: E402


class _GateTestBase(unittest.TestCase):
    """Sets up isolated env so the gate looks at our tmp state."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._state_path = os.path.join(self._tmp.name, "brr.json")
        self._audit_dir = os.path.join(self._tmp.name, "audit")
        self._prev = {k: os.environ.pop(k, None) for k in
                      ("BROKER_REPAIR_REQUIRED_PATH",
                       "AUDIT_TRADING_DIR",
                       "KILL_SWITCH")}
        os.environ["BROKER_REPAIR_REQUIRED_PATH"] = self._state_path
        os.environ["AUDIT_TRADING_DIR"] = self._audit_dir

    def tearDown(self) -> None:
        for k in ("BROKER_REPAIR_REQUIRED_PATH",
                  "AUDIT_TRADING_DIR",
                  "KILL_SWITCH"):
            os.environ.pop(k, None)
            if self._prev.get(k) is not None:
                os.environ[k] = self._prev[k]
        self._tmp.cleanup()

    # Default helper: all checks affirmatively pass.
    # v3.29 ETAP 2 added _read_safe_mode_consistency as a higher-priority
    # blocker than broker_repair_required. We patch it to a clear state so
    # v3.28-era assertions continue to evaluate the intended blocker.
    def _patch_all_clear(self):
        sm_inactive = sm.SafeModeState.inactive()
        return [
            patch.object(gate, "_read_safe_mode",
                         return_value=(False, "")),
            patch.object(gate, "_read_broker_repair",
                         return_value=set()),
            patch.object(gate, "_read_incident_detector_latest",
                         return_value={}),
            patch.object(gate, "_read_equity_gap_pct",
                         return_value=0.1),
            patch.object(gate, "_read_position_reconciliation_age_seconds",
                         return_value=60.0),
            patch.object(gate, "_is_us_market_hours",
                         return_value=True),
            patch.object(gate, "_read_kill_switch",
                         return_value=False),
            patch.object(gate, "_read_safe_mode_consistency",
                         return_value={"blocker": None,
                                        "verdict": "CONSISTENT"}),
        ]


class TestAllocatorIncidentGate(_GateTestBase):
    def test_01_default_block_unknown_on_error(self):
        with patch.object(gate, "_make_snapshot",
                          side_effect=RuntimeError("boom")):
            r = gate.evaluate()
        self.assertIs(r.decision, gate.AllocatorIncidentDecision.BLOCK_UNKNOWN)
        self.assertTrue(any("gate_exception" in b for b in r.blockers))

    def test_02_safe_mode_blocks(self):
        patches = self._patch_all_clear()
        patches[0] = patch.object(gate, "_read_safe_mode",
                                  return_value=(True, "safe_mode active"))
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            r = gate.evaluate()
        self.assertIs(r.decision,
                      gate.AllocatorIncidentDecision.BLOCK_SAFE_MODE_ACTIVE)

    def test_03_broker_repair_blocks(self):
        patches = self._patch_all_clear()
        patches[1] = patch.object(gate, "_read_broker_repair",
                                  return_value={"AVAXUSD"})
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            r = gate.evaluate()
        self.assertIs(r.decision,
                      gate.AllocatorIncidentDecision.BLOCK_BROKER_REPAIR_REQUIRED)

    def test_04_p13_blocks(self):
        today = datetime.now(timezone.utc).date().isoformat()
        det = {
            "findings": [
                {"pattern": "P13_bracket_interlock_blocked_close",
                 "severity": "CRITICAL",
                 "ts_iso": f"{today}T12:00:00+00:00"},
            ]
        }
        patches = self._patch_all_clear()
        patches[2] = patch.object(gate, "_read_incident_detector_latest",
                                  return_value=det)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            r = gate.evaluate()
        self.assertIs(r.decision,
                      gate.AllocatorIncidentDecision.BLOCK_P13_ACTIVE)

    def test_05_equity_gap_above_2pct_blocks(self):
        patches = self._patch_all_clear()
        patches[3] = patch.object(gate, "_read_equity_gap_pct",
                                  return_value=3.5)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            r = gate.evaluate()
        self.assertIs(r.decision,
                      gate.AllocatorIncidentDecision.BLOCK_EQUITY_GAP_UNRESOLVED)

    def test_06_equity_gap_0_5_to_2_pct_does_not_block(self):
        patches = self._patch_all_clear()
        patches[3] = patch.object(gate, "_read_equity_gap_pct",
                                  return_value=1.2)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            r = gate.evaluate()
        self.assertIs(r.decision,
                      gate.AllocatorIncidentDecision.ALLOW_ALLOCATOR)

    def test_07_position_recon_stale_blocks(self):
        patches = self._patch_all_clear()
        patches[4] = patch.object(gate, "_read_position_reconciliation_age_seconds",
                                  return_value=3 * 3600.0)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            r = gate.evaluate()
        self.assertIs(r.decision,
                      gate.AllocatorIncidentDecision.BLOCK_POSITION_RECONCILIATION_STALE)

    def test_08_kill_switch_blocks(self):
        patches = self._patch_all_clear()
        patches[6] = patch.object(gate, "_read_kill_switch",
                                  return_value=True)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            r = gate.evaluate()
        self.assertIs(r.decision,
                      gate.AllocatorIncidentDecision.BLOCK_KILL_SWITCH)

    def test_09_allow_only_when_all_clear(self):
        patches = self._patch_all_clear()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            r = gate.evaluate()
        self.assertIs(r.decision,
                      gate.AllocatorIncidentDecision.ALLOW_ALLOCATOR)
        self.assertEqual(r.blockers, ())

    def test_10_audit_row_written(self):
        patches = self._patch_all_clear()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            r = gate.evaluate()
            gate.write_audit_decision(r)
        date = datetime.now(timezone.utc).date().isoformat()
        audit_path = Path(self._audit_dir) / f"{date}.jsonl"
        self.assertTrue(audit_path.exists())
        lines = [json.loads(l) for l in audit_path.read_text().splitlines() if l.strip()]
        kinds = [l.get("decision_type") for l in lines]
        self.assertIn("ALLOCATOR_INCIDENT_GATE_DECISION", kinds)

    def test_11_no_broker_call(self):
        """The gate module must never call alpaca_orders or use sockets."""
        # AST check (also asserted in test_12 but easier-to-debug version).
        path = _REPO_ROOT / "shared" / "allocator_incident_gate.py"
        src = path.read_text(encoding="utf-8")
        for word in ("submit_order", "place_order", "safe_close",
                     "cancel_order", "close_position"):
            self.assertNotIn(word, src,
                             f"allocator_incident_gate must not reference {word}")

    def test_12_ast_no_alpaca(self):
        path = _REPO_ROOT / "shared" / "allocator_incident_gate.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden = {"alpaca_orders", "shared.alpaca_orders"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertNotIn(n.name, forbidden)
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, forbidden)

    def test_13_allocator_calls_gate_before_buy(self):
        """scripts/execute_allocation_plan.py must evaluate the gate
        BEFORE any AccountAwareAllocator.execute_orders code path."""
        path = _REPO_ROOT / "scripts" / "execute_allocation_plan.py"
        src = path.read_text(encoding="utf-8")
        idx_gate = src.find("allocator_incident_gate")
        idx_alloc = src.find("from allocator import AccountAwareAllocator")
        self.assertGreater(idx_gate, -1, "gate not imported in allocator script")
        self.assertGreater(idx_alloc, -1, "AccountAwareAllocator import missing")
        self.assertLess(idx_gate, idx_alloc,
                        "gate must be evaluated BEFORE allocator instantiation")

    def test_14_allocator_exits_clean_when_blocked(self):
        """When the gate refuses, main() must return 0 (clean exit) and
        write the block doc."""
        path = _REPO_ROOT / "scripts" / "execute_allocation_plan.py"
        src = path.read_text(encoding="utf-8")
        # Must call write_block_doc inside the refused branch.
        self.assertIn("_write_block_doc", src)
        # The refused branch must return 0 (clean exit).
        # Easiest semantic check: find the literal "return 0" right after
        # the block-doc write.
        idx_doc = src.index("_write_block_doc(gate_result")
        tail = src[idx_doc: idx_doc + 600]
        self.assertIn("return 0", tail,
                      "blocked allocator must return 0 (clean exit)")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
