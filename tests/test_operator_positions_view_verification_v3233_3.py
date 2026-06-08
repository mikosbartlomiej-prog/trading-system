"""v3.23.3.3 (2026-06-08) — operator Positions / View All verification.

After v3.23.3.2 (Orders view = no open orders), the operator
explicitly verified the Alpaca paper Positions / View All panel:

- Open equity positions visible: NONE.
- Open crypto positions visible: ETHUSD + AVAXUSD meaningful;
  SOLUSD + LTCUSD dust.

The "no equity" finding does NOT mean "no positions" — crypto is
still open. These tests pin that distinction across all four
machine-readable artifacts and the human-readable investigation
doc.

READ-ONLY. No orders placed, no positions touched, no live endpoint
called.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

GH_ACTIONS_JSON = (REPO_ROOT / "learning-loop"
                     / "position_reconciliation"
                     / "amd_close_source_gh_actions_investigation_latest.json")
AUDIT_BYPASS_JSON = (REPO_ROOT / "learning-loop"
                       / "position_reconciliation"
                       / "audit_bypass_investigation_latest.json")
LATEST_JSON = (REPO_ROOT / "learning-loop"
                 / "position_reconciliation" / "latest.json")
SNAPSHOT_JSON = (REPO_ROOT / "learning-loop"
                   / "position_reconciliation"
                   / "operator_dashboard_snapshot.json")
INVESTIGATION_MD = (REPO_ROOT / "docs"
                     / "AMD_CLOSE_SOURCE_INVESTIGATION.md")


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# Status tokens added in v3.23.3.3 (must appear).
ADDED_TOKENS = (
    "OPERATOR_VERIFIED_NO_OPEN_EQUITY_POSITIONS",
    "OPERATOR_VERIFIED_OPEN_CRYPTO_POSITIONS_PRESENT",
    "OPERATOR_VERIFIED_CRYPTO_POSITIONS_ETH_AVAX_SOL_LTC",
)
# Status token explicitly withheld (must NOT appear in any
# "tokens added" list — though it may be referenced as withheld
# rationale).
WITHHELD_TOKEN = "OPERATOR_VERIFIED_NO_OPEN_POSITIONS"

# Status token carried over from v3.23.3.2 (must remain present).
CARRY_OVER_NO_ORDERS = "OPERATOR_VERIFIED_NO_OPEN_ORDERS_ALL_FILLED_OR_CANCELED"


class TestAddedTokensPresentEverywhere(unittest.TestCase):
    def test_added_tokens_in_gh_actions_json(self):
        data = _load(GH_ACTIONS_JSON)
        b = data["operator_positions_view_verification_2026_06_08_v3233_3"]
        for t in ADDED_TOKENS:
            self.assertIn(t, b["status_tokens_added"])

    def test_added_tokens_in_audit_bypass_json(self):
        data = _load(AUDIT_BYPASS_JSON)
        b = data["operator_positions_view_verification_2026_06_08_v3233_3"]
        for t in ADDED_TOKENS:
            self.assertIn(t, b["status_tokens"])

    def test_added_tokens_in_latest_json(self):
        data = _load(LATEST_JSON)
        b = data["v3233_3_followups"]
        for t in ADDED_TOKENS:
            self.assertIn(t, b["status_tokens_added"])

    def test_added_tokens_in_snapshot_json(self):
        data = _load(SNAPSHOT_JSON)
        b = data["v3233_3_positions_view_verification_2026_06_08"]
        for t in ADDED_TOKENS:
            self.assertIn(t, b["status_tokens_added"])

    def test_added_tokens_in_investigation_md(self):
        text = INVESTIGATION_MD.read_text(encoding="utf-8")
        for t in ADDED_TOKENS:
            self.assertIn(t, text)


class TestNoOpenPositionsTokenWithheld(unittest.TestCase):
    """OPERATOR_VERIFIED_NO_OPEN_POSITIONS must NOT appear in the
    ``added`` token sets in any artifact. It may only be cited in
    explicit ``withheld`` lists."""

    def _added_lists_do_not_contain_withheld(self, *added_lists):
        for tokens in added_lists:
            self.assertNotIn(WITHHELD_TOKEN, tokens)

    def test_gh_actions_added_list_excludes_withheld(self):
        data = _load(GH_ACTIONS_JSON)
        b = data["operator_positions_view_verification_2026_06_08_v3233_3"]
        self._added_lists_do_not_contain_withheld(b["status_tokens_added"])
        self.assertIn(WITHHELD_TOKEN,
                       b["status_tokens_intentionally_withheld"])

    def test_audit_bypass_added_list_excludes_withheld(self):
        data = _load(AUDIT_BYPASS_JSON)
        b = data["operator_positions_view_verification_2026_06_08_v3233_3"]
        self._added_lists_do_not_contain_withheld(b["status_tokens"])

    def test_latest_added_list_excludes_withheld(self):
        data = _load(LATEST_JSON)
        b = data["v3233_3_followups"]
        self._added_lists_do_not_contain_withheld(b["status_tokens_added"])
        self.assertIn(WITHHELD_TOKEN,
                       b["status_tokens_intentionally_withheld"])

    def test_snapshot_added_list_excludes_withheld(self):
        data = _load(SNAPSHOT_JSON)
        b = data["v3233_3_positions_view_verification_2026_06_08"]
        self._added_lists_do_not_contain_withheld(b["status_tokens_added"])
        self.assertIn(WITHHELD_TOKEN,
                       b["status_tokens_intentionally_withheld"])


class TestCarryOverNoOrdersTokenPreserved(unittest.TestCase):
    """v3.23.3.2 added OPERATOR_VERIFIED_NO_OPEN_ORDERS_ALL_FILLED_OR_CANCELED;
    that fact must remain visible after v3.23.3.3."""

    def test_no_orders_token_still_in_gh_actions(self):
        data = _load(GH_ACTIONS_JSON)
        b = data["operator_order_state_verification_2026_06_08_v3233_2"]
        self.assertIn(CARRY_OVER_NO_ORDERS, b["status_tokens_added"])

    def test_no_orders_token_still_in_audit_bypass(self):
        data = _load(AUDIT_BYPASS_JSON)
        b = data["operator_order_state_verification_2026_06_08_v3233_2"]
        self.assertIn(CARRY_OVER_NO_ORDERS, b["status_tokens"])

    def test_no_orders_token_still_in_latest(self):
        data = _load(LATEST_JSON)
        b = data["v3233_2_followups"]
        self.assertIn(CARRY_OVER_NO_ORDERS, b["status_tokens_added"])


class TestCryptoPositionsRecordedVerbatim(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = _load(SNAPSHOT_JSON)
        cls.gh = _load(GH_ACTIONS_JSON)
        block = cls.snapshot["v3233_3_positions_view_verification_2026_06_08"]
        cls.positions_by_sym = {p["symbol"]: p
                                  for p in block["open_crypto_positions_visible"]}

    def test_ethusd_meaningful_values(self):
        p = self.positions_by_sym["ETHUSD"]
        self.assertFalse(p["dust"])
        self.assertTrue(p["meaningful"])
        self.assertAlmostEqual(p["qty"], 5.0724058, places=7)
        self.assertAlmostEqual(p["market_value_usd"], 8674.97, places=2)
        self.assertAlmostEqual(p["avg_entry_price_usd"], 1575.2766,
                                places=4)
        self.assertAlmostEqual(p["cost_basis_usd"], 7990.4422,
                                places=4)

    def test_avaxusd_meaningful_values(self):
        p = self.positions_by_sym["AVAXUSD"]
        self.assertFalse(p["dust"])
        self.assertTrue(p["meaningful"])
        self.assertAlmostEqual(p["qty"], 365.968010756, places=9)
        self.assertAlmostEqual(p["market_value_usd"], 2514.57, places=2)
        self.assertAlmostEqual(p["avg_entry_price_usd"], 6.82, places=2)
        self.assertAlmostEqual(p["cost_basis_usd"], 2495.9018,
                                places=4)

    def test_ltcusd_dust(self):
        p = self.positions_by_sym["LTCUSD"]
        self.assertTrue(p["dust"])
        self.assertFalse(p["meaningful"])
        self.assertAlmostEqual(p["qty"], 0.000000183, places=12)
        self.assertAlmostEqual(p["market_value_usd"], 0.000008,
                                places=9)
        self.assertAlmostEqual(p["avg_entry_price_usd"], 44.3795,
                                places=4)

    def test_solusd_dust(self):
        p = self.positions_by_sym["SOLUSD"]
        self.assertTrue(p["dust"])
        self.assertFalse(p["meaningful"])
        self.assertAlmostEqual(p["qty"], 0.00000021, places=12)
        self.assertAlmostEqual(p["market_value_usd"], 0.000014,
                                places=9)
        self.assertAlmostEqual(p["avg_entry_price_usd"], 66.3843,
                                places=4)

    def test_source_label_is_operator_dashboard_positions_view_manual(self):
        b = self.snapshot["v3233_3_positions_view_verification_2026_06_08"]
        self.assertEqual(b["source"],
                          "OPERATOR_DASHBOARD_POSITIONS_VIEW_MANUAL")

    def test_no_equity_positions_visible(self):
        b = self.snapshot["v3233_3_positions_view_verification_2026_06_08"]
        self.assertEqual(b["open_equity_positions_visible"], [])
        self.assertEqual(b["open_equity_positions_visible_count"], 0)

    def test_unrealized_pnl_computed_locally_only(self):
        """ETH + AVAX have computed unrealized P/L; SOL + LTC do
        NOT (would be noise). NONE of these are 'realized'."""
        p = self.positions_by_sym["ETHUSD"]
        # 8674.97 - 7990.4422 = 684.5278
        self.assertAlmostEqual(p["unrealized_pl_usd_computed_locally"],
                                684.5278, places=4)
        p = self.positions_by_sym["AVAXUSD"]
        # 2514.57 - 2495.9018 = 18.6682
        self.assertAlmostEqual(p["unrealized_pl_usd_computed_locally"],
                                18.6682, places=4)
        # Dust positions: unrealized_pl is null (not synthesized).
        for sym in ("LTCUSD", "SOLUSD"):
            self.assertIsNone(
                self.positions_by_sym[sym]
                ["unrealized_pl_usd_computed_locally"],
            )


class TestMeaningfulAndDustSplitInOtherJSON(unittest.TestCase):
    def test_audit_bypass_lists_split(self):
        data = _load(AUDIT_BYPASS_JSON)
        b = data["operator_positions_view_verification_2026_06_08_v3233_3"]
        self.assertEqual(set(b["open_crypto_meaningful"]),
                          {"ETHUSD", "AVAXUSD"})
        self.assertEqual(set(b["open_crypto_dust"]),
                          {"SOLUSD", "LTCUSD"})

    def test_latest_lists_split(self):
        data = _load(LATEST_JSON)
        b = data["v3233_3_followups"]
        self.assertEqual(set(b["open_crypto_meaningful"]),
                          {"ETHUSD", "AVAXUSD"})
        self.assertEqual(set(b["open_crypto_dust"]),
                          {"SOLUSD", "LTCUSD"})


class TestAMDFactsUnchanged(unittest.TestCase):
    def test_amd_pnl_minus_437_07_in_gh_actions(self):
        data = _load(GH_ACTIONS_JSON)
        b = data["operator_positions_view_verification_2026_06_08_v3233_3"]
        self.assertAlmostEqual(b["amd_realized_pnl_usd_unchanged"],
                                -437.07, places=2)

    def test_amd_pnl_minus_437_07_in_latest(self):
        data = _load(LATEST_JSON)
        b = data["v3233_3_followups"]
        self.assertAlmostEqual(b["amd_realized_pnl_usd_unchanged"],
                                -437.07, places=2)

    def test_amd_source_still_requires_alpaca_api_or_export(self):
        for path in (GH_ACTIONS_JSON, AUDIT_BYPASS_JSON, LATEST_JSON):
            data = _load(path)
            text = json.dumps(data)
            self.assertIn(
                "AMD_CLOSE_SOURCE_REQUIRES_ALPACA_API_ORDER_DETAILS_OR_EXPORT",
                text,
            )

    def test_client_order_id_status_unchanged(self):
        data = _load(GH_ACTIONS_JSON)
        b = data["operator_positions_view_verification_2026_06_08_v3233_3"]
        self.assertEqual(
            b["client_order_id_status_unchanged"],
            "CLIENT_ORDER_ID_NOT_VISIBLE_IN_UI_TABLE",
        )

    def test_amd_close_source_not_marked_resolved(self):
        data = _load(GH_ACTIONS_JSON)
        self.assertIsNone(data["confirmed_source"])
        b = data["operator_positions_view_verification_2026_06_08_v3233_3"]
        self.assertFalse(b["risk_impact"]
                            ["amd_close_submitter_source_resolved"])


class TestRiskImpactClarified(unittest.TestCase):
    def test_equity_batch_not_open(self):
        data = _load(GH_ACTIONS_JSON)
        b = data["operator_positions_view_verification_2026_06_08_v3233_3"]
        self.assertTrue(b["risk_impact"]
                          ["equity_2026_06_04_batch_not_open_per_dashboard"])

    def test_crypto_meaningful_open(self):
        data = _load(GH_ACTIONS_JSON)
        b = data["operator_positions_view_verification_2026_06_08_v3233_3"]
        self.assertTrue(b["risk_impact"]
                          ["crypto_positions_open_meaningful_eth_avax"])

    def test_dust_not_auto_closed(self):
        data = _load(GH_ACTIONS_JSON)
        b = data["operator_positions_view_verification_2026_06_08_v3233_3"]
        self.assertTrue(b["risk_impact"]
                          ["crypto_positions_dust_sol_ltc_not_auto_closed"])

    def test_do_not_infer_realized_pnl_for_crypto(self):
        data = _load(GH_ACTIONS_JSON)
        b = data["operator_positions_view_verification_2026_06_08_v3233_3"]
        self.assertTrue(b["risk_impact"]
                          ["do_not_infer_realized_pnl_for_crypto_from_market_value"])


class TestSafetyFlagsUnchanged(unittest.TestCase):
    def test_edge_gate_not_enabled(self):
        v = os.environ.get("EDGE_GATE_ENABLED", "false").lower()
        self.assertIn(v, ("false", "0", "no", ""))

    def test_allow_broker_paper_not_enabled(self):
        v = os.environ.get("ALLOW_BROKER_PAPER", "false").lower()
        self.assertIn(v, ("false", "0", "no", ""))

    def test_audit_bypass_invariant_still_satisfied(self):
        data = _load(AUDIT_BYPASS_JSON)
        scan = data["static_scan_summary"]
        self.assertTrue(scan["invariant_satisfied"])
        self.assertEqual(scan["flagged_files"], [])

    def test_no_active_legacy_dangerous_invariant(self):
        import audit_bypass_detector as abd
        self.assertTrue(abd.NO_ACTIVE_LEGACY_DANGEROUS_ORDER_SCRIPT)
        r = abd.detect_bypasses(REPO_ROOT)
        self.assertEqual(r["flagged_files"], [])
        self.assertTrue(r["invariant_satisfied"])


class TestVersionAndPriorBlocksPreserved(unittest.TestCase):
    def test_gh_actions_version_in_3233_family(self):
        self.assertTrue(
            _load(GH_ACTIONS_JSON)["version"].startswith("v3.23.3."),
        )

    def test_audit_bypass_version_in_3233_family(self):
        self.assertTrue(
            _load(AUDIT_BYPASS_JSON)["version"].startswith("v3.23.3."),
        )

    def test_latest_version_in_3233_family(self):
        self.assertTrue(
            _load(LATEST_JSON)["version"].startswith("v3.23.3."),
        )

    def test_all_prior_followup_blocks_preserved(self):
        data = _load(LATEST_JSON)
        for key in (
            "v3233_3_followups", "v3233_2_followups",
            "v3233_1_followups", "v3233_followups",
            "v3232_followups",
        ):
            self.assertIn(key, data,
                            f"prior followup block dropped: {key}")


if __name__ == "__main__":
    unittest.main()
