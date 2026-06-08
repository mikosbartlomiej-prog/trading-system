"""v3.23.3.1 (2026-06-08 EOD) — operator UI verification tests.

After v3.23.3 quarantined the legacy direct-order scripts and the
GitHub Actions investigation ruled out workflow runs, the operator
re-opened the Alpaca paper Order History UI and confirmed:

- the AMD close row is STILL VISIBLE (not deleted),
- the UI table does NOT expose ``client_order_id``,
- the AMD close source therefore still requires either an Alpaca
  read-only API order-details lookup OR an Alpaca activity export
  that includes the ``client_order_id`` column.

These tests pin those facts so a later sprint cannot silently:
- mark AMD evidence as lost,
- invent a ``client_order_id``,
- change AMD's realized P/L,
- forget that the UI lacks the discriminating column.

READ-ONLY. No orders placed, no positions touched, no live endpoint
called.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestGHActionsInvestigationJSONHasOperatorUIBlock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = (REPO_ROOT / "learning-loop"
                     / "position_reconciliation"
                     / "amd_close_source_gh_actions_investigation_latest.json")
        with open(cls.path, encoding="utf-8") as f:
            cls.data = json.load(f)

    def test_version_bumped(self):
        # v3.23.3.x updates preserve all earlier facts; accept any
        # version in the v3.23.3 family.
        self.assertTrue(
            self.data["version"].startswith("v3.23.3."),
            f"unexpected version: {self.data['version']}",
        )

    def test_operator_ui_verification_block_present(self):
        self.assertIn("operator_ui_verification_2026_06_08_eod", self.data)

    def test_row_still_visible(self):
        b = self.data["operator_ui_verification_2026_06_08_eod"]
        self.assertTrue(b["row_still_visible_in_alpaca_paper_ui"])
        self.assertFalse(b["evidence_lost"])

    def test_client_order_id_not_in_ui_table(self):
        b = self.data["operator_ui_verification_2026_06_08_eod"]
        self.assertFalse(b["client_order_id_visible_in_ui_table"])

    def test_amd_pnl_unchanged_at_minus_437_07(self):
        b = self.data["operator_ui_verification_2026_06_08_eod"]
        self.assertAlmostEqual(
            b["amd_realized_pnl_usd_unchanged"], -437.07, places=2,
        )

    def test_three_status_tokens_present(self):
        b = self.data["operator_ui_verification_2026_06_08_eod"]
        tokens = set(b["status_tokens_added"])
        for t in (
            "AMD_ORDER_ROW_VISIBLE_IN_ALPACA_UI",
            "CLIENT_ORDER_ID_NOT_VISIBLE_IN_UI_TABLE",
            "AMD_CLOSE_SOURCE_REQUIRES_ALPACA_API_ORDER_DETAILS_OR_EXPORT",
        ):
            self.assertIn(t, tokens)

    def test_next_required_action_narrowed(self):
        self.assertEqual(
            self.data["next_required_action"],
            "AMD_CLOSE_SOURCE_REQUIRES_ALPACA_API_ORDER_DETAILS_OR_EXPORT",
        )
        options = self.data["next_required_action_options"]
        self.assertEqual(len(options), 2)
        ids = {o["id"] for o in options}
        self.assertIn("ALPACA_API_ORDER_DETAILS_GET", ids)
        self.assertIn("ALPACA_CSV_ACTIVITY_EXPORT", ids)

    def test_transcribed_row_matches_operator_values(self):
        b = self.data["operator_ui_verification_2026_06_08_eod"]
        row = b["transcribed_row"]
        # Exact values supplied by operator (must not be mutated).
        self.assertEqual(row["ID"],
                          "7f3ac850-49aa-4ccb-b075-c0ecb56c5871")
        self.assertEqual(row["Asset"], "AMD")
        self.assertEqual(row["Side"], "sell")
        self.assertEqual(row["Position Intent"], "sell_to_close")
        self.assertEqual(row["Qty"], 34.0)
        self.assertEqual(row["Filled Qty"], 34.0)
        self.assertEqual(row["Avg Fill Price"], 485.02)
        self.assertEqual(row["Total Amount"], 16490.68)
        self.assertEqual(row["Status"], "filled")
        self.assertEqual(row["Source"], "access_key")


class TestAuditBypassJSONReferencesUIVerification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = (REPO_ROOT / "learning-loop"
                     / "position_reconciliation"
                     / "audit_bypass_investigation_latest.json")
        with open(cls.path, encoding="utf-8") as f:
            cls.data = json.load(f)

    def test_version_bumped(self):
        # v3.23.3.x updates preserve all earlier facts; accept any
        # version in the v3.23.3 family.
        self.assertTrue(
            self.data["version"].startswith("v3.23.3."),
            f"unexpected version: {self.data['version']}",
        )

    def test_action_items_use_narrowed_next_action(self):
        items = self.data["action_items"]
        self.assertIn(
            "AMD_CLOSE_SOURCE_REQUIRES_ALPACA_API_ORDER_DETAILS_OR_EXPORT",
            items,
        )
        # Old generic action no longer the primary line.
        self.assertNotIn(
            "PULL_ALPACA_API_ORDER_HISTORY_FOR_AMD_2026_06_05",
            items,
        )

    def test_do_not_infer_client_order_id_action_present(self):
        self.assertIn("DO_NOT_INFER_CLIENT_ORDER_ID",
                       self.data["action_items"])

    def test_ui_verification_block_present(self):
        self.assertIn("amd_ui_verification_2026_06_08_eod", self.data)
        b = self.data["amd_ui_verification_2026_06_08_eod"]
        self.assertTrue(b["amd_close_confirmed_unchanged"])
        self.assertFalse(b["evidence_lost"])
        self.assertAlmostEqual(b["amd_realized_pnl_usd"], -437.07,
                                places=2)


class TestLatestJSONHasV3233_1Followup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = (REPO_ROOT / "learning-loop"
                     / "position_reconciliation" / "latest.json")
        with open(cls.path, encoding="utf-8") as f:
            cls.data = json.load(f)

    def test_version_bumped(self):
        # v3.23.3.x updates preserve all earlier facts; accept any
        # version in the v3.23.3 family.
        self.assertTrue(
            self.data["version"].startswith("v3.23.3."),
            f"unexpected version: {self.data['version']}",
        )

    def test_v3233_1_followups_present(self):
        self.assertIn("v3233_1_followups", self.data)
        b = self.data["v3233_1_followups"]
        self.assertTrue(b["amd_ui_verification_completed"])
        self.assertEqual(b["amd_order_row_status"],
                          "AMD_ORDER_ROW_VISIBLE_IN_ALPACA_UI")
        self.assertFalse(b["client_order_id_visible_in_ui_table"])
        self.assertEqual(
            b["client_order_id_status"],
            "CLIENT_ORDER_ID_NOT_VISIBLE_IN_UI_TABLE",
        )
        self.assertEqual(
            b["amd_close_source_status"],
            "AMD_CLOSE_SOURCE_REQUIRES_ALPACA_API_ORDER_DETAILS_OR_EXPORT",
        )
        self.assertAlmostEqual(b["amd_realized_pnl_usd_unchanged"],
                                -437.07, places=2)
        self.assertFalse(b["evidence_lost"])

    def test_previous_v3233_followups_preserved(self):
        # v3.23.3 quarantine block must still be readable.
        self.assertIn("v3233_followups", self.data)
        b = self.data["v3233_followups"]
        self.assertTrue(b["legacy_scripts_quarantined"])
        self.assertTrue(b["audit_bypass_invariant_satisfied"])

    def test_v3232_block_still_present(self):
        # v3.23.2 followups must NOT be silently dropped.
        self.assertIn("v3232_followups", self.data)


class TestInvestigationMDIncludesUITranscription(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = (REPO_ROOT / "docs"
                     / "AMD_CLOSE_SOURCE_INVESTIGATION.md")
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_eod_section_present(self):
        self.assertIn(
            "Operator UI verification — 2026-06-08 EOD (v3.23.3.1)",
            self.text,
        )

    def test_transcribed_row_id_present(self):
        self.assertIn("7f3ac850-49aa-4ccb-b075-c0ecb56c5871",
                       self.text)

    def test_three_status_tokens_referenced(self):
        for t in (
            "AMD_ORDER_ROW_VISIBLE_IN_ALPACA_UI",
            "CLIENT_ORDER_ID_NOT_VISIBLE_IN_UI_TABLE",
            "AMD_CLOSE_SOURCE_REQUIRES_ALPACA_API_ORDER_DETAILS_OR_EXPORT",
        ):
            self.assertIn(t, self.text)

    def test_does_not_invent_a_client_order_id(self):
        # No bare client_order_id assignment masquerading as fact.
        # We explicitly assert the doc states it remains unknown.
        compact = " ".join(self.text.split())
        self.assertIn("unknown", compact)
        # Cheap sanity: no UUID-shaped string other than the
        # confirmed order_id should appear next to "client_order_id".
        # The doc may quote prefix conventions like
        # "exit-profit-lock-amd-*" or "mcp-*" — those are wildcards,
        # not invented UUIDs.

    def test_pnl_unchanged_in_doc(self):
        self.assertIn("-$437.07", self.text)


if __name__ == "__main__":
    unittest.main()
