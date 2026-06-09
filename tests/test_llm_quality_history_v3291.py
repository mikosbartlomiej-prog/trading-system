"""v3.29.1 (2026-06-09) — quality history append + idempotency."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestAppend(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.history_path = self.tmp / "quality_history.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _qrep(self, *, status, provider_used=5, empty=False):
        return {
            "rows_seen": 5,
            "rows_with_provider_used": provider_used,
            "empty_risks_count": 5 if empty else 1,
            "empty_next_actions_count": 5 if empty else 1,
            "zero_confidence_count": 5 if empty else 1,
            "secret_leak_hits": 0, "unsafe_phrase_hits": 0,
        }

    def test_appends_acceptable_with_accepted_true(self):
        import broker_paper_canary_unlock as bp
        e = bp.append_quality_history(
            run_id="r-good",
            quality_status="LLM_ADVISORY_QUALITY_ACCEPTABLE",
            quality_report=self._qrep(
                status="LLM_ADVISORY_QUALITY_ACCEPTABLE"),
            selected_provider="gemini",
            selected_model=None,
            free_only=True,
            history_path=self.history_path,
        )
        self.assertTrue(e["accepted_for_unlock_counting"])

    def test_appends_generic_with_accepted_false(self):
        import broker_paper_canary_unlock as bp
        e = bp.append_quality_history(
            run_id="r-generic",
            quality_status="LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER",
            quality_report=self._qrep(
                status="LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER"),
            selected_provider="gemini",
            selected_model=None,
            free_only=True,
            history_path=self.history_path,
        )
        self.assertFalse(e["accepted_for_unlock_counting"])

    def test_acceptable_with_empty_rows_accepted_false(self):
        # Status says ACCEPTABLE but rows are all-empty — must NOT be
        # accepted for unlock counting.
        import broker_paper_canary_unlock as bp
        e = bp.append_quality_history(
            run_id="r-empty",
            quality_status="LLM_ADVISORY_QUALITY_ACCEPTABLE",
            quality_report=self._qrep(
                status="LLM_ADVISORY_QUALITY_ACCEPTABLE",
                empty=True),
            selected_provider="gemini",
            selected_model=None,
            free_only=True,
            history_path=self.history_path,
        )
        self.assertFalse(e["accepted_for_unlock_counting"])

    def test_idempotent_on_run_id(self):
        import broker_paper_canary_unlock as bp
        for _ in range(3):
            bp.append_quality_history(
                run_id="r-dup",
                quality_status="LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER",
                quality_report=self._qrep(
                    status="LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER"),
                selected_provider="gemini",
                selected_model=None, free_only=True,
                history_path=self.history_path,
            )
        rows = [
            json.loads(l)
            for l in self.history_path.read_text(
                encoding="utf-8").splitlines() if l.strip()
        ]
        self.assertEqual(len(rows), 1)

    def test_history_does_not_leak_secrets(self):
        import broker_paper_canary_unlock as bp
        bp.append_quality_history(
            run_id="r-ok",
            quality_status="LLM_ADVISORY_QUALITY_ACCEPTABLE",
            quality_report=self._qrep(
                status="LLM_ADVISORY_QUALITY_ACCEPTABLE"),
            selected_provider="gemini",
            selected_model=None, free_only=True,
            history_path=self.history_path,
        )
        text = self.history_path.read_text(encoding="utf-8")
        for k in ("GEMINI_API_KEY=", "AIza", "sk-ant-", "ALPACA_API_KEY="):
            self.assertNotIn(k, text)


if __name__ == "__main__":
    unittest.main()
