"""v3.23.2 (2026-06-08) — AMD close source static-search tests."""

from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

import amd_close_source_search as acs


class TestClassifyResult(unittest.TestCase):
    def test_no_matches_yields_not_found(self):
        cls = acs.classify_search_result([])
        self.assertEqual(
            cls,
            acs.AMD_CLOSE_SOURCE_NOT_FOUND_LOCAL_LOGS_REQUIRE_GH_ACTIONS_OR_API_HISTORY,
        )

    def test_only_weak_yields_not_found(self):
        cls = acs.classify_search_result(
            [{"file": "x.py", "line_number": 1,
              "content_excerpt": "...",
              "match_strength": acs.WEAK}],
        )
        self.assertEqual(
            cls,
            acs.AMD_CLOSE_SOURCE_NOT_FOUND_LOCAL_LOGS_REQUIRE_GH_ACTIONS_OR_API_HISTORY,
        )

    def test_strong_match_yields_identified(self):
        cls = acs.classify_search_result(
            [{"file": "x.py", "line_number": 1,
              "content_excerpt": "...",
              "match_strength": acs.STRONG}],
        )
        self.assertEqual(cls, acs.AMD_CLOSE_SOURCE_IDENTIFIED)


class TestSearchAmdClose(unittest.TestCase):
    def test_missing_local_source_classified_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # No journal/, no scripts/. Just an empty repo.
            r = acs.search_amd_close(root)
            self.assertEqual(
                r["classification"],
                acs.AMD_CLOSE_SOURCE_NOT_FOUND_LOCAL_LOGS_REQUIRE_GH_ACTIONS_OR_API_HISTORY,
            )
            self.assertIsNone(r["confirmed_path"])
            self.assertIn("INVESTIGATE_AMD_CLOSE_SOURCE_IN_GITHUB_ACTIONS",
                            r["followup_required"])

    def test_strong_match_identifies_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "journal").mkdir()
            (root / "journal/x.jsonl").write_text(
                f'{{"order_id": "{acs.TARGET_ORDER_ID}", "symbol": "AMD"}}\n',
            )
            r = acs.search_amd_close(root)
            self.assertEqual(r["classification"],
                              acs.AMD_CLOSE_SOURCE_IDENTIFIED)
            self.assertEqual(r["confirmed_path"], "journal/x.jsonl")

    def test_self_reference_filter_excludes_position_reconciliation(self):
        """Reports in position_reconciliation/ mention the order_id but
        are NOT evidence of the close source."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "learning-loop" / "position_reconciliation").mkdir(
                parents=True,
            )
            (root / "learning-loop" / "position_reconciliation"
              / "report.json").write_text(
                f'{{"close_order_id": "{acs.TARGET_ORDER_ID}"}}\n',
            )
            r = acs.search_amd_close(root)
            # Self-referenced match excluded → unknown.
            self.assertEqual(
                r["classification"],
                acs.AMD_CLOSE_SOURCE_NOT_FOUND_LOCAL_LOGS_REQUIRE_GH_ACTIONS_OR_API_HISTORY,
            )

    def test_weak_matches_collected_as_suspected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "scripts/x.py").write_text(textwrap.dedent('''
                # AMD will sell_to_close
                pass
            '''))
            r = acs.search_amd_close(root)
            self.assertEqual(
                r["classification"],
                acs.AMD_CLOSE_SOURCE_NOT_FOUND_LOCAL_LOGS_REQUIRE_GH_ACTIONS_OR_API_HISTORY,
            )
            self.assertIn("scripts/x.py", r["suspected_paths"])


class TestRealRepoSearchProducedReport(unittest.TestCase):
    """The committed search-result JSON must match real-repo state."""

    def test_report_exists(self):
        path = (REPO_ROOT / "learning-loop"
                 / "position_reconciliation"
                 / "amd_close_source_search_latest.json")
        self.assertTrue(path.exists())

    def test_report_classification_unknown_for_now(self):
        path = (REPO_ROOT / "learning-loop"
                 / "position_reconciliation"
                 / "amd_close_source_search_latest.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # No confirmed local source as of v3.23.2 build.
        self.assertEqual(
            data["classification"],
            acs.AMD_CLOSE_SOURCE_NOT_FOUND_LOCAL_LOGS_REQUIRE_GH_ACTIONS_OR_API_HISTORY,
        )
        self.assertIsNone(data["confirmed_path"])
        self.assertEqual(data["target_order_id"], acs.TARGET_ORDER_ID)


class TestInvariants(unittest.TestCase):
    def test_module_is_read_only_by_contract(self):
        self.assertTrue(acs.NEVER_PLACES_ORDERS)
        self.assertTrue(acs.NEVER_CALLS_LIVE_API)
        self.assertTrue(acs.NEVER_SPECULATES_AS_FACT)


if __name__ == "__main__":
    unittest.main()
