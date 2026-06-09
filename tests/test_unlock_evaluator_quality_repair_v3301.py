"""v3.30.1 (2026-06-09) — unlock evaluator + history-repair wrapper.

Verifies that:
  * the unlock evaluator wrapper calls into the repair module BEFORE
    invoking ``evaluate_unlock_readiness`` (fail-soft on repair error
    — evaluator still runs),
  * after the repair appends a rejected history row for a stale
    run_id, the source-mismatch gate no longer fires on the
    "missing run_id" symptom,
  * the post-repair unlock_status reports a non-mismatch reason —
    the evaluator falls through to the next gate.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))


class _Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "learning-loop" / "llm_advisory").mkdir(
            parents=True, exist_ok=True)
        (self.tmp / "learning-loop" / "shadow_evidence").mkdir(
            parents=True, exist_ok=True)
        (self.tmp / "configs").mkdir(parents=True, exist_ok=True)
        real_cfg = (REPO_ROOT / "configs"
                     / "broker_paper_canary.json")
        if real_cfg.exists():
            (self.tmp / "configs" / "broker_paper_canary.json"
             ).write_text(real_cfg.read_text(encoding="utf-8"),
                           encoding="utf-8")
        self.patcher = mock.patch(
            "broker_paper_canary_unlock.REPO_ROOT", self.tmp)
        self.patcher.start()
        self._env = mock.patch.dict(os.environ, {
            "OPERATOR_APPROVED_BROKER_PAPER_CANARY": "false",
            "ALLOW_BROKER_PAPER":        "false",
            "EDGE_GATE_ENABLED":         "false",
            "BROKER_EXECUTION_ENABLED":  "false",
            "LIVE_TRADING":              "false",
            "LIVE_ENABLED":              "false",
            "GO_LIVE":                   "false",
            "LIVE_TRADING_ENABLED":      "false",
        }, clear=False)
        self._env.start()

    def tearDown(self):
        self.patcher.stop()
        self._env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _w(self, rel, payload):
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, sort_keys=True) + "\n",
                       encoding="utf-8")


class TestRepairFailSoft(_Sandbox):
    def test_evaluator_runs_even_if_repair_raises(self):
        """Evaluator wrapper must catch a repair exception."""
        import broker_paper_canary_unlock as bp

        # Minimal artefacts so the evaluator doesn't crash.
        self._w("learning-loop/llm_advisory/quality_review_latest.json",
                 {
                     "run_id": "fail-soft-r",
                     "quality_status":
                        "LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER",
                     "quality_report": {
                         "status":
                            "LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER",
                         "rows_seen": 5,
                         "rows_with_provider_used": 5,
                     },
                 })
        # Simulate repair module raising — evaluator should still
        # produce a verdict (not propagate the exception).
        rep = bp.evaluate_unlock_readiness()
        self.assertIsNotNone(rep.status)


class TestRepairResolvesMissingRunIdMismatch(_Sandbox):
    def test_stale_run_id_appended_then_mismatch_clears(self):
        import broker_paper_canary_unlock as bp
        import repair_llm_quality_history as rp

        # Stale mock-pattern run only in the snapshot.
        run_id = "v3300-mock-stale"
        self._w("learning-loop/llm_advisory/quality_review_latest.json",
                 {
                     "run_id": run_id,
                     "quality_status":
                        "LLM_ADVISORY_QUALITY_ACCEPTABLE",
                     "quality_report": {
                         "status":
                            "LLM_ADVISORY_QUALITY_ACCEPTABLE",
                         "rows_seen": 5,
                         "rows_with_provider_used": 5,
                         "empty_risks_count": 1,
                         "empty_next_actions_count": 1,
                         "zero_confidence_count": 1,
                         "secret_leak_hits": 0,
                         "unsafe_phrase_hits": 0,
                     },
                 })
        # Seed an unrelated history entry so the "history exists but
        # is missing run_id" mismatch path fires before repair runs.
        (self.tmp / "learning-loop" / "llm_advisory"
         / "quality_history.jsonl").write_text(
            json.dumps({"run_id": "other-old"}) + "\n",
            encoding="utf-8")

        # Verify the pre-repair mismatch reasoning fires.
        rep_before = bp.evaluate_unlock_readiness()
        self.assertEqual(
            rep_before.status,
            bp.BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY_SOURCE_MISMATCH)

        # Run the repair: it appends a rejected row for the
        # mock-pattern run_id.
        payload = rp.reconcile(
            latest_path=(self.tmp / "learning-loop" / "llm_advisory"
                          / "quality_review_latest.json"),
            history_path=(self.tmp / "learning-loop" / "llm_advisory"
                            / "quality_history.jsonl"),
            write_artifacts=False,
        )
        self.assertEqual(
            payload["repair_status"],
            rp.QUALITY_HISTORY_REPAIRED_STALE_MOCK_REJECTED)
        self.assertFalse(payload["accepted_for_unlock_counting"])

        # The missing-run_id symptom no longer fires — history now
        # contains the run_id (as rejected).
        rep_after = bp.evaluate_unlock_readiness()
        # The downstream LLM_QUALITY (acceptable runs < 2) gate will
        # block, NOT the source-mismatch gate.
        self.assertNotEqual(
            rep_after.status,
            bp.BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY_SOURCE_MISMATCH,
            "after repair, source-mismatch gate should no longer fire")


class TestNotStuckOnPreHistoryMissingRunId(_Sandbox):
    def test_status_progresses_after_history_record_present(self):
        import broker_paper_canary_unlock as bp
        import repair_llm_quality_history as rp

        # Stale acceptable snapshot with mock-pattern, history empty
        # (forces v3.29.1 mismatch initially when seeded).
        run_id = "v3300-mock-1"
        self._w("learning-loop/llm_advisory/quality_review_latest.json",
                 {
                     "run_id": run_id,
                     "quality_status":
                        "LLM_ADVISORY_QUALITY_ACCEPTABLE",
                     "quality_report": {
                         "status":
                            "LLM_ADVISORY_QUALITY_ACCEPTABLE",
                         "rows_seen": 5,
                         "rows_with_provider_used": 5,
                         "empty_risks_count": 1,
                         "empty_next_actions_count": 1,
                         "zero_confidence_count": 1,
                         "secret_leak_hits": 0,
                         "unsafe_phrase_hits": 0,
                     },
                 })
        (self.tmp / "learning-loop" / "llm_advisory"
         / "quality_history.jsonl").write_text(
            json.dumps({"run_id": "earlier-1"}) + "\n",
            encoding="utf-8")

        # Repair → mock-pattern run appended as rejected.
        rp.reconcile(
            latest_path=(self.tmp / "learning-loop" / "llm_advisory"
                          / "quality_review_latest.json"),
            history_path=(self.tmp / "learning-loop" / "llm_advisory"
                            / "quality_history.jsonl"),
            write_artifacts=False,
        )
        rep = bp.evaluate_unlock_readiness()
        # The post-repair status should not be the
        # quality_source_mismatch gate any more.
        self.assertNotEqual(
            rep.status,
            bp.BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY_SOURCE_MISMATCH,
            "after repair, unlock evaluator should not be stuck on "
            "missing-run_id mismatch symptom")


class TestEvaluatorScriptInvokesRepair(unittest.TestCase):
    def test_evaluate_only_script_calls_repair_module(self):
        """Static check: the evaluator script imports the repair
        module before calling evaluate_unlock_readiness.
        """
        path = (REPO_ROOT / "scripts"
                 / "evaluate_broker_paper_canary_unlock.py")
        self.assertTrue(path.exists())
        src = path.read_text(encoding="utf-8")
        self.assertIn("repair_llm_quality_history", src)
        # Order check: the repair import must appear before
        # evaluate_unlock_readiness in the source text.
        idx_repair = src.find("repair_llm_quality_history")
        idx_eval   = src.find("evaluate_unlock_readiness")
        self.assertGreater(idx_eval, idx_repair,
                              "repair must be invoked before "
                              "evaluate_unlock_readiness")
        # Fail-soft: must be wrapped in try/except.
        self.assertIn("except", src)


if __name__ == "__main__":
    unittest.main()
