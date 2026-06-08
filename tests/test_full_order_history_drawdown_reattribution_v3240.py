"""v3.24.0 (2026-06-08) — full order-history drawdown reattribution.

Operator provided the broader Alpaca paper Order History export.
The 7-symbol equity batch is now fully reconstructed and the
v3.23.x interim hypothesis ("remaining 7 equity trades likely
explain ~-$5,304") is OBSOLETE. The major drawdown source is the
SOL/LTC realized close cycle on 2026-06-06.

These tests pin:
- the 7 non-AMD equity P/L sums to +$200.33,
- the full 8-symbol equity batch P/L sums to -$236.74,
- the SOL realized loss is approx -$2,851.15,
- the LTC realized loss is approx -$2,742.90,
- combined SOL+LTC approx -$5,594.06,
- the old hypothesis is no longer the current truth,
- no realized P/L is inferred from currently open ETH/AVAX,
- no trading flag was flipped,
- AMD P/L and AMD source status are unchanged.

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

LATEST_JSON = (REPO_ROOT / "learning-loop"
                 / "position_reconciliation" / "latest.json")
MANUAL_HIST_JSON = (REPO_ROOT / "learning-loop"
                      / "position_reconciliation"
                      / "manual_order_history_remaining_2026-06-04.json")
SNAPSHOT_JSON = (REPO_ROOT / "learning-loop"
                   / "position_reconciliation"
                   / "operator_dashboard_snapshot.json")
INCIDENT_MD = REPO_ROOT / "docs" / "INCIDENT_2026_06_07.md"
RECONCILIATION_MD = REPO_ROOT / "docs" / "BROKER_STATE_RECONCILIATION.md"
TRADE_RECONSTRUCTION_MD = REPO_ROOT / "docs" / "TRADE_RECONSTRUCTION.md"
POSITION_LATEST_MD = REPO_ROOT / "docs" / "position_reconciliation_LATEST.md"


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# Expected verbatim P/L values per operator's Order History export.
EXPECTED_EQUITY_PNL = {
    "CRWD": -136.58,
    "NOW":  -30.38,
    "QQQ":  -6.95,
    "SPY":  18.78,
    "GLD":  -25.22,
    "PANW": -51.04,
    "ORCL": 431.72,
    "AMD":  -437.07,
}
EXPECTED_NON_AMD_SUM = 200.33
EXPECTED_FULL_SUM = -236.74

EXPECTED_SOL_PNL_APPROX = -2851.15
EXPECTED_LTC_PNL_APPROX = -2742.90
EXPECTED_CRYPTO_COMBINED_APPROX = -5594.06


class TestManualHistoryReconstructed(unittest.TestCase):
    """Every entry must have real avg fill values now, not nulls."""

    @classmethod
    def setUpClass(cls):
        cls.data = _load(MANUAL_HIST_JSON)
        cls.by_symbol = {s["symbol"]: s for s in cls.data["symbols"]}

    def test_version_bumped_to_v3240(self):
        self.assertEqual(self.data["version"], "v3.24.0")

    def test_all_seven_non_amd_symbols_complete(self):
        for sym in ("CRWD", "NOW", "QQQ", "SPY", "GLD", "PANW", "ORCL"):
            entry = self.by_symbol[sym]
            self.assertEqual(entry["data_quality"],
                              "COMPLETE_FROM_OPERATOR_EXPORT")
            # No nulls remain on essential fields.
            self.assertIsNotNone(entry["open_avg_fill_price"])
            self.assertIsNotNone(entry["close_avg_fill_price"])
            self.assertIsNotNone(entry["realized_pnl_usd"])

    def test_amd_also_listed_with_known_pnl(self):
        amd = self.by_symbol["AMD"]
        self.assertEqual(amd["data_quality"],
                          "COMPLETE_FROM_OPERATOR_EXPORT")
        self.assertAlmostEqual(amd["realized_pnl_usd"], -437.07,
                                places=2)
        self.assertEqual(amd["close_order_id"],
                          "7f3ac850-49aa-4ccb-b075-c0ecb56c5871")

    def test_per_symbol_pnl_matches_export(self):
        for sym, expected in EXPECTED_EQUITY_PNL.items():
            actual = self.by_symbol[sym]["realized_pnl_usd"]
            self.assertAlmostEqual(actual, expected, places=2,
                                     msg=f"{sym} P/L mismatch")

    def test_non_amd_sum_is_plus_200_33(self):
        total = sum(
            self.by_symbol[s]["realized_pnl_usd"]
            for s in EXPECTED_EQUITY_PNL if s != "AMD"
        )
        self.assertAlmostEqual(total, EXPECTED_NON_AMD_SUM, places=2)

    def test_full_8_symbol_sum_is_minus_236_74(self):
        total = sum(s["realized_pnl_usd"] for s in self.data["symbols"])
        self.assertAlmostEqual(total, EXPECTED_FULL_SUM, places=2)


class TestLatestJSONReattribution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = _load(LATEST_JSON)

    def test_version_at_least_v324(self):
        # v3.24+ updates (v3.25, ...) preserve the v324_followups
        # block. Real invariant: that block exists (asserted next).
        v = self.data["version"]
        self.assertTrue(
            v.startswith("v3.24") or v.startswith("v3.25")
            or v.startswith("v3.26"),
            f"unexpected version family: {v}",
        )

    def test_v324_followups_block_present(self):
        self.assertIn("v324_followups", self.data)

    def test_old_hypothesis_marked_obsolete(self):
        b = self.data["v324_followups"]
        self.assertEqual(b["old_hypothesis_obsolete"]["status"],
                          "OBSOLETE_DISPROVED_BY_OPERATOR_EXPORT")
        # Must mention the old wrong dollar figure so future readers
        # see what was replaced.
        self.assertIn("5,304",
                       b["old_hypothesis_obsolete"]["claim"]
                       .replace(",", ",").replace("$", ""))

    def test_equity_batch_totals_match_export(self):
        b = self.data["v324_followups"]["equity_batch_reconstruction"]
        self.assertAlmostEqual(b["non_amd_7_symbols_total_usd"],
                                EXPECTED_NON_AMD_SUM, places=2)
        self.assertAlmostEqual(b["full_8_symbol_batch_total_usd"],
                                EXPECTED_FULL_SUM, places=2)

    def test_per_symbol_pnl_recorded(self):
        b = (self.data["v324_followups"]
             ["equity_batch_reconstruction"]
             ["per_symbol_realized_pnl_usd"])
        for sym, expected in EXPECTED_EQUITY_PNL.items():
            self.assertAlmostEqual(b[sym], expected, places=2)

    def test_crypto_sol_ltc_block_present(self):
        b = (self.data["v324_followups"]
             ["crypto_close_cycle_reattribution_2026_06_06"])
        self.assertAlmostEqual(
            b["SOLUSD"]["realized_pnl_usd_approx"],
            EXPECTED_SOL_PNL_APPROX, places=2,
        )
        self.assertAlmostEqual(
            b["LTCUSD"]["realized_pnl_usd_approx"],
            EXPECTED_LTC_PNL_APPROX, places=2,
        )
        self.assertAlmostEqual(
            b["combined_realized_pnl_usd_approx"],
            EXPECTED_CRYPTO_COMBINED_APPROX, places=2,
        )

    def test_drawdown_attribution_status_near_complete(self):
        att = self.data["v324_followups"]["drawdown_attribution"]
        self.assertEqual(
            att["status"],
            "DRAWDOWN_ATTRIBUTION_NEAR_COMPLETE_WITH_SMALL_RESIDUAL",
        )
        # Reported drawdown unchanged.
        self.assertAlmostEqual(att["reported_drawdown_usd"], -5741.0,
                                places=2)
        # Equity contribution matches the export.
        self.assertAlmostEqual(att["equity_batch_contribution_usd"],
                                EXPECTED_FULL_SUM, places=2)
        # Crypto contribution matches.
        self.assertAlmostEqual(
            att["crypto_sol_ltc_close_cycle_contribution_usd_approx"],
            EXPECTED_CRYPTO_COMBINED_APPROX, places=2,
        )

    def test_six_status_tokens_added(self):
        tokens = self.data["v324_followups"]["status_tokens_added"]
        for t in (
            "EQUITY_BATCH_RECONSTRUCTED_FROM_ORDER_HISTORY",
            "EQUITY_BATCH_NOT_PRIMARY_DRAWDOWN_SOURCE",
            "CRYPTO_SOL_LTC_REALIZED_LOSS_CONFIRMED",
            "DRAWDOWN_REATTRIBUTED_TO_CRYPTO_CLOSE_CYCLE",
            "DRAWDOWN_ATTRIBUTION_NEAR_COMPLETE_WITH_SMALL_RESIDUAL",
            "RESIDUAL_DRAWDOWN_REQUIRES_ACCOUNT_EQUITY_TIMING_RECONCILIATION",
        ):
            self.assertIn(t, tokens)

    def test_risk_finding_carries_action_item(self):
        rf = self.data["v324_followups"]["risk_findings"]
        self.assertEqual(
            rf["action_item"],
            "INVESTIGATE_CRYPTO_POSITION_SIZING_AND_EXIT_POLICY_SOL_LTC_2026_06_06",
        )
        # Must include at least 6 specific operational questions.
        self.assertGreaterEqual(len(rf["questions_to_answer"]), 6)

    def test_all_prior_followup_blocks_preserved(self):
        for key in (
            "v324_followups", "v3233_3_followups", "v3233_2_followups",
            "v3233_1_followups", "v3233_followups", "v3232_followups",
        ):
            self.assertIn(key, self.data,
                            f"prior followup block dropped: {key}")


class TestOldHypothesisRemovedAsCurrentTruth(unittest.TestCase):
    """The phrase 'remaining 7 equity trades likely explain ~-$5,304'
    must no longer be presented as the CURRENT truth anywhere. It
    may appear only as documented obsolete history."""

    OBSOLETE_FRAGMENT = "remaining 7 equity trades likely explain"

    def test_old_hypothesis_only_appears_as_obsolete(self):
        for path in (LATEST_JSON,):
            data = _load(path)
            blob = json.dumps(data)
            if self.OBSOLETE_FRAGMENT in blob:
                # If present, it must be inside an OBSOLETE marker.
                idx = blob.find(self.OBSOLETE_FRAGMENT)
                window = blob[max(0, idx - 200):idx + 400]
                self.assertTrue(
                    "OBSOLETE_DISPROVED" in window
                    or "OBSOLETE" in window,
                    f"old hypothesis present without OBSOLETE marker in "
                    f"{path.name}",
                )

    def test_manual_history_does_not_quote_the_5304_guess_as_fact(self):
        data = _load(MANUAL_HIST_JSON)
        # The 'remaining_pnl_to_explain_usd_approx': -5304 from the
        # v3.23.2 placeholder MUST NOT be the current truth statement.
        # Either it is removed, OR it lives under an OBSOLETE block.
        if "remaining_pnl_to_explain_usd_approx" in data:
            # Allowed only if explicitly tagged obsolete.
            self.fail(
                "remaining_pnl_to_explain_usd_approx still at top "
                "level — must be removed in v3.24 or wrapped under "
                "old_hypothesis_obsolete",
            )
        self.assertIn("old_hypothesis_obsolete", data)
        self.assertEqual(
            data["old_hypothesis_obsolete"]["status"],
            "OBSOLETE_DISPROVED_BY_OPERATOR_EXPORT_2026_06_08",
        )


class TestCryptoNoUnrealizedPnLInferenceFromOpenETHAVAX(unittest.TestCase):
    """The currently-open ETH/AVAX positions must NOT have a
    realized P/L synthesized from market value."""

    def test_snapshot_only_locally_computed_unrealized(self):
        data = _load(SNAPSHOT_JSON)
        block = data["v3233_3_positions_view_verification_2026_06_08"]
        for pos in block["open_crypto_positions_visible"]:
            # The field name must explicitly be unrealized + locally
            # computed.
            self.assertIn("unrealized_pl_usd_computed_locally", pos)
            # Realized-P/L field must NOT be present for open positions.
            self.assertNotIn("realized_pnl_usd", pos)

    def test_latest_v324_does_not_attribute_open_eth_avax_to_drawdown(self):
        data = _load(LATEST_JSON)
        att = data["v324_followups"]["drawdown_attribution"]
        # ETH/AVAX must not appear as drawdown contributors.
        blob = json.dumps(att)
        self.assertNotIn("ETHUSD", blob)
        self.assertNotIn("AVAXUSD", blob)


class TestAMDFactsUnchanged(unittest.TestCase):
    def test_amd_pnl_minus_437_07_in_latest(self):
        data = _load(LATEST_JSON)
        b = data["v324_followups"]["preserved_facts"]
        self.assertAlmostEqual(b["amd_realized_pnl_usd"], -437.07,
                                places=2)

    def test_amd_source_still_requires_alpaca_api_or_export(self):
        data = _load(LATEST_JSON)
        b = data["v324_followups"]["preserved_facts"]
        self.assertEqual(
            b["amd_close_source_status"],
            "AMD_CLOSE_SOURCE_REQUIRES_ALPACA_API_ORDER_DETAILS_OR_EXPORT",
        )
        self.assertEqual(
            b["client_order_id_status"],
            "CLIENT_ORDER_ID_NOT_VISIBLE_IN_UI_TABLE",
        )


class TestSafetyFlagsUnchanged(unittest.TestCase):
    def test_edge_gate_not_enabled(self):
        v = os.environ.get("EDGE_GATE_ENABLED", "false").lower()
        self.assertIn(v, ("false", "0", "no", ""))

    def test_allow_broker_paper_not_enabled(self):
        v = os.environ.get("ALLOW_BROKER_PAPER", "false").lower()
        self.assertIn(v, ("false", "0", "no", ""))

    def test_drawdown_guard_still_active_in_latest(self):
        data = _load(LATEST_JSON)
        self.assertTrue(
            data["v324_followups"]["preserved_facts"]
            ["drawdown_guard_active"],
        )

    def test_baseline_not_reset_in_latest(self):
        data = _load(LATEST_JSON)
        self.assertFalse(
            data["v324_followups"]["preserved_facts"]["baseline_reset"],
        )

    def test_audit_bypass_invariant_still_satisfied(self):
        import audit_bypass_detector as abd
        r = abd.detect_bypasses(REPO_ROOT)
        self.assertTrue(r["invariant_satisfied"])
        self.assertEqual(r["flagged_files"], [])
        self.assertTrue(abd.NO_ACTIVE_LEGACY_DANGEROUS_ORDER_SCRIPT)


class TestDocsReferenceReattribution(unittest.TestCase):
    """Each of the 4 updated docs must reference the v3.24
    reattribution and the new action item."""

    PATHS = (INCIDENT_MD, RECONCILIATION_MD,
              TRADE_RECONSTRUCTION_MD, POSITION_LATEST_MD)

    def test_each_doc_mentions_v324(self):
        for p in self.PATHS:
            text = p.read_text(encoding="utf-8")
            self.assertIn("v3.24.0", text, f"missing in {p.name}")

    def test_crypto_sol_ltc_referenced_in_drawdown_docs(self):
        # SOL/LTC reattribution belongs in the three drawdown /
        # incident / state-tracking docs. TRADE_RECONSTRUCTION.md is
        # scoped to the equity batch and intentionally defers to
        # those docs for the crypto reattribution.
        drawdown_docs = (
            INCIDENT_MD, RECONCILIATION_MD, POSITION_LATEST_MD,
        )
        for p in drawdown_docs:
            text = p.read_text(encoding="utf-8")
            self.assertIn("SOL", text, f"missing SOL ref in {p.name}")
            self.assertIn("LTC", text, f"missing LTC ref in {p.name}")

    def test_trade_reconstruction_doc_links_to_incident_or_latest(self):
        # TRADE_RECONSTRUCTION.md must point readers to where the
        # crypto reattribution lives so it isn't lost.
        text = TRADE_RECONSTRUCTION_MD.read_text(encoding="utf-8")
        self.assertTrue(
            "INCIDENT_2026_06_07" in text or "latest.json" in text,
            "TRADE_RECONSTRUCTION must reference INCIDENT doc or "
            "latest.json for crypto reattribution",
        )

    def test_incident_doc_lists_new_action_item(self):
        text = INCIDENT_MD.read_text(encoding="utf-8")
        self.assertIn(
            "INVESTIGATE_CRYPTO_POSITION_SIZING_AND_EXIT_POLICY_SOL_LTC_2026_06_06",
            text,
        )


class TestNoTradingActionsIntroduced(unittest.TestCase):
    """v3.24 must NOT introduce code that places or modifies
    orders; it is a documentation + reattribution sprint only."""

    def test_no_order_placement_helper_added(self):
        # Inspect git status would be ideal but is not available
        # in this test runner. Instead: no new .py outside tests/
        # should appear that calls requests.post(/v2/orders).
        import audit_bypass_detector as abd
        r = abd.detect_bypasses(REPO_ROOT)
        self.assertEqual(r["flagged_files"], [])


if __name__ == "__main__":
    unittest.main()
