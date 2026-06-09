"""v3.29.1 (2026-06-09) — quality-source mismatch blocks unlock."""

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
            "ALLOW_BROKER_PAPER": "false",
            "EDGE_GATE_ENABLED":  "false",
            "BROKER_EXECUTION_ENABLED": "false",
            "LIVE_TRADING": "false", "LIVE_ENABLED": "false",
            "GO_LIVE": "false", "LIVE_TRADING_ENABLED": "false",
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


class TestMismatchBetweenTopAndReportStatus(_Sandbox):
    def test_top_acceptable_but_report_generic_blocks(self):
        import broker_paper_canary_unlock as bp
        self._w("learning-loop/llm_advisory/quality_review_latest.json",
                 {
                     "quality_status": "LLM_ADVISORY_QUALITY_ACCEPTABLE",
                     "quality_report": {
                         "status": "LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER",
                         "rows_seen": 5,
                         "rows_with_provider_used": 5,
                     },
                 })
        rep = bp.evaluate_unlock_readiness()
        self.assertEqual(
            rep.status,
            bp.BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY_SOURCE_MISMATCH)


class TestStaleQualityArtifactBlocks(_Sandbox):
    def test_run_id_missing_from_history_blocks(self):
        import broker_paper_canary_unlock as bp
        self._w("learning-loop/llm_advisory/quality_review_latest.json",
                 {
                     "run_id": "stale-r",
                     "quality_status":
                        "LLM_ADVISORY_QUALITY_ACCEPTABLE",
                     "quality_report": {
                         "status":
                            "LLM_ADVISORY_QUALITY_ACCEPTABLE",
                     },
                 })
        # history exists but does not contain stale-r
        (self.tmp / "learning-loop" / "llm_advisory"
         / "quality_history.jsonl").write_text(
            json.dumps({"run_id": "other"}) + "\n",
            encoding="utf-8")
        rep = bp.evaluate_unlock_readiness()
        self.assertEqual(
            rep.status,
            bp.BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY_SOURCE_MISMATCH)


class TestNoMismatchPassesThrough(_Sandbox):
    def test_consistent_artefact_does_not_block_on_mismatch(self):
        import broker_paper_canary_unlock as bp
        self._w("learning-loop/llm_advisory/quality_review_latest.json",
                 {
                     "run_id": "r1",
                     "quality_status":
                        "LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER",
                     "quality_report": {
                         "status":
                            "LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER",
                         "rows_seen": 5,
                         "rows_with_provider_used": 5,
                     },
                 })
        rep = bp.evaluate_unlock_readiness()
        # No mismatch — falls through to the next gate (no-real-record).
        self.assertNotEqual(
            rep.status,
            bp.BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY_SOURCE_MISMATCH)


if __name__ == "__main__":
    unittest.main()
