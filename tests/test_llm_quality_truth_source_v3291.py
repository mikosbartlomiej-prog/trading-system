"""v3.29.1 (2026-06-09) — quality truth source + anti-mock tests."""

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
        self.patcher = mock.patch(
            "broker_paper_canary_unlock.REPO_ROOT", self.tmp)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_latest(self, payload):
        p = (self.tmp / "learning-loop" / "llm_advisory"
              / "quality_review_latest.json")
        p.write_text(
            json.dumps(payload, sort_keys=True) + "\n",
            encoding="utf-8")

    def _write_history(self, rows):
        p = (self.tmp / "learning-loop" / "llm_advisory"
              / "quality_history.jsonl")
        with p.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, sort_keys=True) + "\n")


class TestAntiMockEmptyAnalysisRejects(_Sandbox):
    def test_acceptable_status_with_all_empty_rows_rejected(self):
        import broker_paper_canary_unlock as bp
        self.assertFalse(
            bp._quality_row_passes_anti_mock({
                "rows_seen": 5,
                "rows_with_provider_used": 5,
                "empty_risks_count": 5,
                "empty_next_actions_count": 5,
                "zero_confidence_count": 5,
                "secret_leak_hits": 0,
                "unsafe_phrase_hits": 0,
            }))


class TestAntiMockSecretLeakRejects(_Sandbox):
    def test_secret_leak_rejects(self):
        import broker_paper_canary_unlock as bp
        self.assertFalse(
            bp._quality_row_passes_anti_mock({
                "rows_seen": 5, "rows_with_provider_used": 5,
                "secret_leak_hits": 1, "unsafe_phrase_hits": 0,
                "empty_risks_count": 0,
                "empty_next_actions_count": 0,
                "zero_confidence_count": 0,
            }))


class TestAntiMockNoProviderUsedRejects(_Sandbox):
    def test_provider_used_zero_rejects(self):
        import broker_paper_canary_unlock as bp
        self.assertFalse(
            bp._quality_row_passes_anti_mock({
                "rows_seen": 5, "rows_with_provider_used": 0,
                "secret_leak_hits": 0, "unsafe_phrase_hits": 0,
            }))


class TestRealQualityRowPasses(_Sandbox):
    def test_genuine_acceptable_passes(self):
        import broker_paper_canary_unlock as bp
        self.assertTrue(
            bp._quality_row_passes_anti_mock({
                "rows_seen": 5, "rows_with_provider_used": 5,
                "empty_risks_count": 1,
                "empty_next_actions_count": 1,
                "zero_confidence_count": 1,
                "secret_leak_hits": 0, "unsafe_phrase_hits": 0,
            }))


class TestUnlockReadsAuthoritativeSource(_Sandbox):
    def test_latest_generic_yields_zero_acceptable_runs(self):
        import broker_paper_canary_unlock as bp
        self._write_latest({
            "quality_status": "LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER",
            "quality_report": {
                "status": "LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER",
                "rows_seen": 5, "rows_with_provider_used": 5,
            },
        })
        self.assertEqual(bp._count_acceptable_quality_runs(), 0)

    def test_latest_acceptable_without_anti_mock_pass_is_zero(self):
        import broker_paper_canary_unlock as bp
        # All-empty rows → acceptable status overruled.
        self._write_latest({
            "quality_status": "LLM_ADVISORY_QUALITY_ACCEPTABLE",
            "quality_report": {
                "status": "LLM_ADVISORY_QUALITY_ACCEPTABLE",
                "rows_seen": 5,
                "rows_with_provider_used": 5,
                "empty_risks_count": 5,
                "empty_next_actions_count": 5,
                "zero_confidence_count": 5,
            },
        })
        self.assertEqual(bp._count_acceptable_quality_runs(), 0)


class TestHistoryDistinctRunsCounted(_Sandbox):
    def test_two_distinct_acceptable_runs_count_2(self):
        import broker_paper_canary_unlock as bp
        self._write_history([
            {"run_id": "r1",
             "quality_status": "LLM_ADVISORY_QUALITY_ACCEPTABLE",
             "accepted_for_unlock_counting": True},
            {"run_id": "r2",
             "quality_status": "LLM_ADVISORY_QUALITY_ACCEPTABLE",
             "accepted_for_unlock_counting": True},
        ])
        self.assertEqual(bp._count_acceptable_quality_runs(), 2)

    def test_same_run_id_dedup(self):
        import broker_paper_canary_unlock as bp
        self._write_history([
            {"run_id": "r1",
             "quality_status": "LLM_ADVISORY_QUALITY_ACCEPTABLE",
             "accepted_for_unlock_counting": True},
            {"run_id": "r1",
             "quality_status": "LLM_ADVISORY_QUALITY_ACCEPTABLE",
             "accepted_for_unlock_counting": True},
        ])
        self.assertEqual(bp._count_acceptable_quality_runs(), 1)

    def test_history_accepted_false_does_not_count(self):
        import broker_paper_canary_unlock as bp
        self._write_history([
            {"run_id": "r1",
             "quality_status": "LLM_ADVISORY_QUALITY_ACCEPTABLE",
             "accepted_for_unlock_counting": False},
        ])
        self.assertEqual(bp._count_acceptable_quality_runs(), 0)


class TestNoBrokerImports(unittest.TestCase):
    def test_source_clean(self):
        src = (REPO_ROOT / "shared"
                / "broker_paper_canary_unlock.py").read_text(encoding="utf-8")
        for tok in ("alpaca_orders", "place_stock_bracket",
                     "execute_stock_signal"):
            self.assertNotIn(tok, src)


if __name__ == "__main__":
    unittest.main()
