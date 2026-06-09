"""v3.30.1 (2026-06-09) — LLM quality history self-healing repair.

Verifies that ``scripts/repair_llm_quality_history.py``:
  * appends a rejected history row when the latest run is mock-pattern,
  * blocks (and appends rejected) when the artefact's top status
    disagrees with the embedded report.status,
  * appends an accepted history row only when ALL anti-mock guards
    pass AND the top status is ACCEPTABLE,
  * is idempotent / append-only — never deletes a history row,
  * refuses on truthy broker/live env flags,
  * never imports or references alpaca_orders / submit_order /
    place_order / safe_close.
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
sys.path.insert(0, str(REPO_ROOT / "scripts"))


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.latest_path = self.tmp / "quality_review_latest.json"
        self.history_path = self.tmp / "quality_history.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_latest(self, payload):
        self.latest_path.write_text(
            json.dumps(payload, sort_keys=True) + "\n",
            encoding="utf-8")

    def _read_history(self):
        if not self.history_path.exists():
            return []
        return [
            json.loads(l) for l in
            self.history_path.read_text(
                encoding="utf-8").splitlines() if l.strip()
        ]

    def _good_qrep(self, status):
        return {
            "status": status,
            "rows_seen": 5,
            "rows_with_provider_used": 5,
            "empty_risks_count": 1,
            "empty_next_actions_count": 1,
            "zero_confidence_count": 1,
            "secret_leak_hits": 0,
            "unsafe_phrase_hits": 0,
        }


class TestMockRunIdRejected(_Base):
    def test_mock_pattern_run_id_appends_rejected_row(self):
        import repair_llm_quality_history as rp
        self._write_latest({
            "run_id": "v3300-mock-1",
            "quality_status": "LLM_ADVISORY_QUALITY_ACCEPTABLE",
            "quality_report": self._good_qrep(
                "LLM_ADVISORY_QUALITY_ACCEPTABLE"),
        })
        payload = rp.reconcile(
            latest_path=self.latest_path,
            history_path=self.history_path,
            write_artifacts=False,
        )
        self.assertEqual(
            payload["repair_status"],
            rp.QUALITY_HISTORY_REPAIRED_STALE_MOCK_REJECTED)
        self.assertFalse(payload["accepted_for_unlock_counting"])
        rows = self._read_history()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["accepted_for_unlock_counting"])

    def test_case_insensitive_mock_pattern(self):
        import repair_llm_quality_history as rp
        for rid in ("V3283-MOCK-3", "test-run-1", "fake-cal-2",
                      "v330-placeholder", "sample-run"):
            self.setUp()  # fresh tmp per case
            self._write_latest({
                "run_id": rid,
                "quality_status": "LLM_ADVISORY_QUALITY_ACCEPTABLE",
                "quality_report": self._good_qrep(
                    "LLM_ADVISORY_QUALITY_ACCEPTABLE"),
            })
            payload = rp.reconcile(
                latest_path=self.latest_path,
                history_path=self.history_path,
                write_artifacts=False,
            )
            self.assertEqual(
                payload["repair_status"],
                rp.QUALITY_HISTORY_REPAIRED_STALE_MOCK_REJECTED,
                f"run_id={rid!r} must be rejected as mock-pattern")
            self.tearDown()


class TestSourceMismatch(_Base):
    def test_top_vs_report_status_mismatch_blocks(self):
        import repair_llm_quality_history as rp
        self._write_latest({
            "run_id": "v3301-real-1",
            "quality_status": "LLM_ADVISORY_QUALITY_ACCEPTABLE",
            "quality_report": self._good_qrep(
                "LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER"),
        })
        payload = rp.reconcile(
            latest_path=self.latest_path,
            history_path=self.history_path,
            write_artifacts=False,
        )
        self.assertEqual(
            payload["repair_status"],
            rp.QUALITY_HISTORY_REPAIR_BLOCKED_SOURCE_MISMATCH)
        self.assertFalse(payload["accepted_for_unlock_counting"])
        rows = self._read_history()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["accepted_for_unlock_counting"])


class TestAlreadyConsistent(_Base):
    def test_run_id_in_history_with_anti_mock_pass_no_op(self):
        import repair_llm_quality_history as rp
        # Pre-populate history with an accepted row.
        self.history_path.write_text(json.dumps({
            "run_id": "v3301-real-1",
            "quality_status": "LLM_ADVISORY_QUALITY_ACCEPTABLE",
            "rows_seen": 5,
            "rows_with_provider_used": 5,
            "empty_risks_count": 1,
            "empty_next_actions_count": 1,
            "zero_confidence_count": 1,
            "secret_leak_hits": 0,
            "unsafe_phrase_hits": 0,
            "accepted_for_unlock_counting": True,
        }, sort_keys=True) + "\n", encoding="utf-8")
        self._write_latest({
            "run_id": "v3301-real-1",
            "quality_status": "LLM_ADVISORY_QUALITY_ACCEPTABLE",
            "quality_report": self._good_qrep(
                "LLM_ADVISORY_QUALITY_ACCEPTABLE"),
        })
        before = len(self._read_history())
        payload = rp.reconcile(
            latest_path=self.latest_path,
            history_path=self.history_path,
            write_artifacts=False,
        )
        self.assertEqual(
            payload["repair_status"],
            rp.QUALITY_HISTORY_ALREADY_CONSISTENT)
        # No new row appended.
        self.assertEqual(len(self._read_history()), before)


class TestAcceptableConfirmed(_Base):
    def test_clean_acceptable_run_appends_accepted(self):
        import repair_llm_quality_history as rp
        self._write_latest({
            "run_id": "v3301-real-1",
            "quality_status": "LLM_ADVISORY_QUALITY_ACCEPTABLE",
            "quality_report": self._good_qrep(
                "LLM_ADVISORY_QUALITY_ACCEPTABLE"),
            "selected_provider": "gemini",
        })
        payload = rp.reconcile(
            latest_path=self.latest_path,
            history_path=self.history_path,
            write_artifacts=False,
        )
        self.assertEqual(
            payload["repair_status"],
            rp.QUALITY_HISTORY_REPAIRED_ACCEPTABLE_CONFIRMED)
        self.assertTrue(payload["accepted_for_unlock_counting"])
        rows = self._read_history()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["accepted_for_unlock_counting"])


class TestAppendOnly(_Base):
    def test_repair_never_deletes_or_rewrites_rows(self):
        import repair_llm_quality_history as rp
        # Two pre-existing rows.
        with self.history_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"run_id": "old-1",
                                 "accepted_for_unlock_counting": False,
                                 "quality_status":
                                     "LLM_ADVISORY_QUALITY_INSUFFICIENT_SAMPLE"
                                 }) + "\n")
            fh.write(json.dumps({"run_id": "old-2",
                                 "accepted_for_unlock_counting": True,
                                 "quality_status":
                                     "LLM_ADVISORY_QUALITY_ACCEPTABLE"
                                 }) + "\n")
        before = self._read_history()
        self.assertEqual(len(before), 2)

        # Process a new mock run.
        self._write_latest({
            "run_id": "new-mock-3",
            "quality_status": "LLM_ADVISORY_QUALITY_ACCEPTABLE",
            "quality_report": self._good_qrep(
                "LLM_ADVISORY_QUALITY_ACCEPTABLE"),
        })
        rp.reconcile(
            latest_path=self.latest_path,
            history_path=self.history_path,
            write_artifacts=False,
        )
        after = self._read_history()
        self.assertGreaterEqual(len(after), len(before),
                                  "history is append-only")
        # Old rows still present, unchanged.
        self.assertEqual(after[0]["run_id"], "old-1")
        self.assertEqual(after[1]["run_id"], "old-2")
        self.assertTrue(after[1]["accepted_for_unlock_counting"])


class TestMissingLatestArtifact(_Base):
    def test_no_latest_file_returns_no_latest_artifact(self):
        import repair_llm_quality_history as rp
        # latest_path does not exist
        payload = rp.reconcile(
            latest_path=self.latest_path,
            history_path=self.history_path,
            write_artifacts=False,
        )
        self.assertEqual(
            payload["repair_status"],
            rp.QUALITY_HISTORY_REPAIR_NO_LATEST_ARTIFACT)
        self.assertFalse(payload["accepted_for_unlock_counting"])
        self.assertEqual(self._read_history(), [])

    def test_latest_with_no_run_id_returns_no_latest_artifact(self):
        import repair_llm_quality_history as rp
        self._write_latest({
            "quality_status": "LLM_ADVISORY_QUALITY_ACCEPTABLE",
            "quality_report": self._good_qrep(
                "LLM_ADVISORY_QUALITY_ACCEPTABLE"),
        })
        payload = rp.reconcile(
            latest_path=self.latest_path,
            history_path=self.history_path,
            write_artifacts=False,
        )
        self.assertEqual(
            payload["repair_status"],
            rp.QUALITY_HISTORY_REPAIR_NO_LATEST_ARTIFACT)


class TestBrokerFlagRefusal(unittest.TestCase):
    def test_refuses_on_truthy_broker_flag(self):
        import repair_llm_quality_history as rp
        with mock.patch.dict(os.environ, {
            "ALLOW_BROKER_PAPER": "true",
        }, clear=False):
            rc = rp.main(["--write-artifacts"])
        self.assertEqual(rc, 1)

    def test_refuses_on_truthy_live_flag(self):
        import repair_llm_quality_history as rp
        with mock.patch.dict(os.environ, {
            "LIVE_TRADING": "true",
        }, clear=False):
            rc = rp.main(["--write-artifacts"])
        self.assertEqual(rc, 1)


class TestNeverImportsBrokerOrders(unittest.TestCase):
    def test_module_does_not_import_or_call_forbidden_symbols(self):
        """The module is allowed to MENTION the forbidden symbols in
        safety comments / docstrings (declaring that it does not use
        them). It must not import them or call them.
        """
        import ast
        path = (REPO_ROOT / "scripts"
                 / "repair_llm_quality_history.py")
        self.assertTrue(path.exists())
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)

        forbidden_imports = {"alpaca_orders"}
        forbidden_calls   = {"submit_order", "place_order",
                              "safe_close"}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(
                        alias.name.split(".")[-1],
                        forbidden_imports,
                        f"repair module must NOT import "
                        f"{alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.assertNotIn(
                        node.module.split(".")[-1],
                        forbidden_imports,
                        f"repair module must NOT import from "
                        f"{node.module}")
                for alias in node.names:
                    self.assertNotIn(
                        alias.name, forbidden_imports,
                        f"repair module must NOT import "
                        f"{alias.name}")
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    self.assertNotIn(
                        func.id, forbidden_calls,
                        f"repair module must NOT call {func.id}")
                elif isinstance(func, ast.Attribute):
                    self.assertNotIn(
                        func.attr, forbidden_calls,
                        f"repair module must NOT call .{func.attr}()")


if __name__ == "__main__":
    unittest.main()
