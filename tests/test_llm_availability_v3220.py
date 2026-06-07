"""v3.22 (2026-06-07) — LLM availability tracker + escalation tests.

After 3 consecutive LLM Senior PM unavailable days, the deterministic
adapter cannot un-flip SILENT-strategy locks. This module tracks
failures and escalates via operator_action_queue.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _isolated_runtime_state(tmpdir):
    """Redirect runtime_state.json to an isolated path."""
    import runtime_state
    runtime_state.RUNTIME_STATE_PATH = Path(tmpdir) / "runtime_state.json"
    return runtime_state


class TestRecordRunCounter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _isolated_runtime_state(self.tmp.name)
        # Re-import to clear cached state
        for mod in ("llm_availability",):
            sys.modules.pop(mod, None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_failure_counter_one(self):
        import llm_availability as la
        with patch.object(la, "_enqueue_action", return_value=None):
            state = la.record_run(success=False, reason="timeout 600s")
        self.assertEqual(state["consecutive_failures"], 1)
        self.assertFalse(state["last_success"])

    def test_success_resets_counter(self):
        import llm_availability as la
        with patch.object(la, "_enqueue_action", return_value=None):
            la.record_run(success=False, reason="t/o")
            la.record_run(success=False, reason="t/o")
        state = la.record_run(success=True, reason="ok")
        self.assertEqual(state["consecutive_failures"], 0)
        self.assertTrue(state["last_success"])

    def test_history_trimmed_to_30(self):
        import llm_availability as la
        with patch.object(la, "_enqueue_action", return_value=None):
            for i in range(35):
                la.record_run(success=(i % 2 == 0), reason=f"r{i}")
        state = la.get_state()
        self.assertLessEqual(len(state.get("history", [])), 30)


class TestEscalation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _isolated_runtime_state(self.tmp.name)
        for mod in ("llm_availability",):
            sys.modules.pop(mod, None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_p0_review_llm_outage_enqueued_at_threshold(self):
        import llm_availability as la
        enqueued = []
        def fake_enqueue(**kwargs):
            enqueued.append(kwargs)
            return kwargs
        with patch.object(la, "_enqueue_action", side_effect=fake_enqueue):
            la.record_run(success=False, reason="timeout")
            state2 = la.record_run(success=False, reason="timeout")
        # 2nd failure should hit P0 threshold (default P0_FAILURE_THRESHOLD=2)
        self.assertEqual(state2["consecutive_failures"], 2)
        # At least one P0 action enqueued
        p0s = [e for e in enqueued
               if e.get("severity") == "P0"
               and e.get("action_type") == "REVIEW_LLM_OUTAGE"]
        self.assertGreaterEqual(len(p0s), 1)

    def test_silent_strategy_lock_escalation_requires_all_conditions(self):
        import llm_availability as la
        # Push to 3 consecutive failures first
        with patch.object(la, "_enqueue_action", return_value=None):
            for _ in range(3):
                la.record_run(success=False, reason="t/o")
        enqueued = []
        def fake_enqueue(**kwargs):
            enqueued.append(kwargs)
            return kwargs
        with patch.object(la, "_enqueue_action", side_effect=fake_enqueue):
            result = la.escalate_silent_strategy_lock(
                strategy="crypto-momentum",
                silent_days=62,
                last_override_iso="2026-05-30T00:00:00+00:00",
            )
        self.assertIsNotNone(result)
        self.assertEqual(len(enqueued), 1)
        self.assertEqual(enqueued[0]["action_type"], "REVIEW_SILENT_STRATEGY_LOCK")
        self.assertEqual(enqueued[0]["severity"], "P1")

    def test_silent_strategy_lock_skipped_below_silent_threshold(self):
        import llm_availability as la
        with patch.object(la, "_enqueue_action", return_value=None):
            for _ in range(3):
                la.record_run(success=False, reason="t/o")
        enqueued = []
        with patch.object(la, "_enqueue_action",
                           side_effect=lambda **kw: enqueued.append(kw)):
            result = la.escalate_silent_strategy_lock(
                strategy="foo", silent_days=5,
            )
        self.assertIsNone(result)
        self.assertEqual(len(enqueued), 0)


class TestInvariants(unittest.TestCase):
    def test_invariants_present_and_true(self):
        import llm_availability as la
        self.assertTrue(la.LLM_OUTAGE_DOES_NOT_BLOCK_RISK_ENGINE)
        self.assertTrue(la.LLM_OUTAGE_DOES_NOT_AUTO_CLEAR_OVERRIDE)

    def test_record_run_does_not_import_alpaca_orders(self):
        # Static check: module source must not import alpaca_orders
        src = (REPO_ROOT / "shared" / "llm_availability.py").read_text()
        self.assertNotIn("from alpaca_orders", src)
        self.assertNotIn("import alpaca_orders", src)
        self.assertNotIn("place_stock_bracket", src)
        self.assertNotIn("safe_close(", src)

    def test_runtime_state_section_registered(self):
        from runtime_state import INTRADAY_SECTIONS
        self.assertIn("llm_availability", INTRADAY_SECTIONS)


class TestNeverAutoClearsOverride(unittest.TestCase):
    """The module must NEVER touch the LLM override lock — operator-only."""

    def test_no_override_mutation_in_source(self):
        src = (REPO_ROOT / "shared" / "llm_availability.py").read_text()
        # Should NOT mutate strategies / state.json overrides
        for forbidden in [
            'state["strategies"]',
            "save_state(",
            "safe_apply_overrides(",
            "set_status(",
            "EDGE_GATE_ENABLED = True",
            "EDGE_GATE_ENABLED=True",
            'os.environ["EDGE_GATE_ENABLED"]',
        ]:
            self.assertNotIn(forbidden, src,
                              f"forbidden override mutation present: {forbidden}")


if __name__ == "__main__":
    unittest.main()
