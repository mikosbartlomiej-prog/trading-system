"""v3.23.3.2 (2026-06-08) — operator no-open-orders verification tests.

After v3.23.3.1, the operator performed an additional Alpaca paper
dashboard check on the Orders view and confirmed there are NO
hanging / open orders (all are filled or canceled). The operator
did **NOT** explicitly verify the Positions / "View All" panel.

These tests pin the precise scope of that verification so a later
sprint cannot silently:
- promote it from order-state to position-state,
- mark all positions as closed,
- change AMD's realized P/L,
- invent a ``client_order_id``,
- mark AMD's close source as resolved,
- flip any kill-switch (live trading / broker_paper / edge gate),
- lower the drawdown guard,
- reset the equity baseline.

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
INVESTIGATION_MD = (REPO_ROOT / "docs"
                     / "AMD_CLOSE_SOURCE_INVESTIGATION.md")


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class TestStatusTokenPresent(unittest.TestCase):
    """The no-open-orders token must appear in all three machine-
    readable artifacts and in the human-readable investigation
    doc."""

    TOKEN = "OPERATOR_VERIFIED_NO_OPEN_ORDERS_ALL_FILLED_OR_CANCELED"

    def test_gh_actions_json_lists_token(self):
        data = _load(GH_ACTIONS_JSON)
        b = data["operator_order_state_verification_2026_06_08_v3233_2"]
        self.assertIn(self.TOKEN, b["status_tokens_added"])

    def test_audit_bypass_json_lists_token(self):
        data = _load(AUDIT_BYPASS_JSON)
        b = data["operator_order_state_verification_2026_06_08_v3233_2"]
        self.assertIn(self.TOKEN, b["status_tokens"])

    def test_latest_json_lists_token(self):
        data = _load(LATEST_JSON)
        b = data["v3233_2_followups"]
        self.assertIn(self.TOKEN, b["status_tokens_added"])

    def test_investigation_md_references_token(self):
        text = INVESTIGATION_MD.read_text(encoding="utf-8")
        self.assertIn(self.TOKEN, text)


class TestNoOpenOrdersDoesNotImplyNoOpenPositions(unittest.TestCase):
    """The order-state verification is intentionally NOT promoted
    to position-state. The OPERATOR_VERIFIED_NO_OPEN_POSITIONS
    token MUST NOT appear anywhere until a separate explicit
    Positions / View All confirmation is performed."""

    FORBIDDEN_TOKEN = "OPERATOR_VERIFIED_NO_OPEN_POSITIONS"

    def test_gh_actions_json_does_not_assert_no_open_positions(self):
        data = _load(GH_ACTIONS_JSON)
        b = data["operator_order_state_verification_2026_06_08_v3233_2"]
        self.assertFalse(b["operator_verified_no_open_positions"])
        self.assertNotIn(self.FORBIDDEN_TOKEN,
                            b["status_tokens_added"])
        # Also nothing elsewhere in this block should claim positions
        # are flat.
        self.assertFalse(b["risk_impact"]["position_flatness_confirmed"])

    def test_audit_bypass_json_does_not_assert_no_open_positions(self):
        data = _load(AUDIT_BYPASS_JSON)
        b = data["operator_order_state_verification_2026_06_08_v3233_2"]
        self.assertFalse(b["operator_verified_no_open_positions"])
        self.assertNotIn(self.FORBIDDEN_TOKEN, b["status_tokens"])

    def test_latest_json_does_not_assert_no_open_positions(self):
        data = _load(LATEST_JSON)
        b = data["v3233_2_followups"]
        self.assertFalse(b["operator_verified_no_open_positions"])
        self.assertNotIn(self.FORBIDDEN_TOKEN, b["status_tokens_added"])

    def test_investigation_md_states_positions_not_inferred(self):
        text = INVESTIGATION_MD.read_text(encoding="utf-8")
        # Must explicitly say that OPERATOR_VERIFIED_NO_OPEN_POSITIONS
        # is NOT added in this section.
        # Slice from the v3.23.3.2 section onward to scope assertion.
        marker = "Operator order-state verification — v3.23.3.2"
        self.assertIn(marker, text)
        section = text.split(marker, 1)[1]
        self.assertIn(self.FORBIDDEN_TOKEN, section)
        self.assertIn("**NOT** added", section)


class TestAMDFactsUnchanged(unittest.TestCase):
    """AMD's realized P/L, order_id, and source-resolution status
    must all be preserved verbatim."""

    def test_amd_pnl_minus_437_07_in_gh_actions_json(self):
        data = _load(GH_ACTIONS_JSON)
        b = data["operator_order_state_verification_2026_06_08_v3233_2"]
        self.assertAlmostEqual(b["amd_realized_pnl_usd_unchanged"],
                                -437.07, places=2)

    def test_amd_pnl_minus_437_07_in_latest_json(self):
        data = _load(LATEST_JSON)
        b = data["v3233_2_followups"]
        self.assertAlmostEqual(b["amd_realized_pnl_usd_unchanged"],
                                -437.07, places=2)

    def test_amd_close_source_status_unchanged_in_gh_actions(self):
        data = _load(GH_ACTIONS_JSON)
        b = data["operator_order_state_verification_2026_06_08_v3233_2"]
        self.assertEqual(
            b["amd_close_source_status_unchanged"],
            "AMD_CLOSE_SOURCE_REQUIRES_ALPACA_API_ORDER_DETAILS_OR_EXPORT",
        )
        self.assertEqual(
            b["client_order_id_status_unchanged"],
            "CLIENT_ORDER_ID_NOT_VISIBLE_IN_UI_TABLE",
        )

    def test_target_order_id_preserved_in_doc(self):
        text = INVESTIGATION_MD.read_text(encoding="utf-8")
        self.assertIn("7f3ac850-49aa-4ccb-b075-c0ecb56c5871", text)

    def test_amd_close_source_not_marked_resolved(self):
        data = _load(GH_ACTIONS_JSON)
        # Top-level confirmed_source must remain null.
        self.assertIsNone(data["confirmed_source"])
        # No invented client_order_id.
        # Each candidate must NOT include a UUID-shaped client_order_id.
        for opt in data["next_required_action_options"]:
            self.assertNotIn("client_order_id_value", opt)


class TestRiskImpactClarified(unittest.TestCase):
    def test_risk_impact_block_present_and_partial(self):
        for path in (GH_ACTIONS_JSON, LATEST_JSON):
            data = _load(path)
            block = (data.get("operator_order_state_verification_2026_06_08_v3233_2")
                       or data.get("v3233_2_followups"))
            ri = block["risk_impact"]
            # No visible stale TP/SL/open-order risk per dashboard.
            self.assertEqual(ri["stale_tp_sl_or_open_order_risk_remaining"],
                              "none-visible")
            # Source still unresolved.
            self.assertFalse(ri["amd_close_submitter_source_resolved"])
            # 7-symbol residual still pending.
            self.assertFalse(ri["remaining_7_symbols_reconstructed"])
            # Positions NOT confirmed flat.
            self.assertFalse(ri["position_flatness_confirmed"])


class TestNextActionsPreserved(unittest.TestCase):
    """The carry-over action items must all still be present."""

    REQUIRED = (
        "AMD_CLOSE_SOURCE_REQUIRES_ALPACA_API_ORDER_DETAILS_OR_EXPORT",
        "PROVIDE_ORDER_HISTORY_FOR_CRWD_NOW_QQQ_SPY_GLD_PANW_ORCL",
        "KEEP_DRAWDOWN_GUARD_ACTIVE",
        "KEEP_EDGE_GATE_DISABLED",
        "DO_NOT_ENABLE_BROKER_PAPER",
        "DO_NOT_RESTORE_QUARANTINED_LEGACY_ORDER_SCRIPTS",
    )

    def test_audit_bypass_action_items_carry_over(self):
        data = _load(AUDIT_BYPASS_JSON)
        items = data["action_items"]
        for token in self.REQUIRED:
            self.assertIn(token, items)


class TestSafetyFlagsUnchanged(unittest.TestCase):
    """No kill-switch may be flipped, no audit invariant lowered."""

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

    def test_no_active_legacy_dangerous_order_script_invariant(self):
        import audit_bypass_detector as abd
        self.assertTrue(abd.NO_ACTIVE_LEGACY_DANGEROUS_ORDER_SCRIPT)
        r = abd.detect_bypasses(REPO_ROOT)
        self.assertEqual(r["flagged_files"], [])
        self.assertTrue(r["invariant_satisfied"])


class TestVersionBumped(unittest.TestCase):
    """v3.23.3.x updates preserve all earlier facts; accept any
    version in the v3.23.3 family. The presence of the v3.23.3.2
    followup block (asserted separately) is what pins this batch."""

    def test_gh_actions_version(self):
        v = _load(GH_ACTIONS_JSON)["version"]
        self.assertTrue(
            v.startswith("v3.23.3.") or v.startswith("v3.24")
            or v.startswith("v3.25") or v.startswith("v3.26"),
            f"unexpected version: {v}",
        )

    def test_audit_bypass_version(self):
        v = _load(AUDIT_BYPASS_JSON)["version"]
        self.assertTrue(
            v.startswith("v3.23.3.") or v.startswith("v3.24")
            or v.startswith("v3.25") or v.startswith("v3.26"),
            f"unexpected version: {v}",
        )

    def test_latest_version(self):
        v = _load(LATEST_JSON)["version"]
        self.assertTrue(
            v.startswith("v3.23.3.") or v.startswith("v3.24")
            or v.startswith("v3.25") or v.startswith("v3.26"),
            f"unexpected version: {v}",
        )

    def test_previous_followup_blocks_preserved(self):
        data = _load(LATEST_JSON)
        for key in ("v3233_2_followups", "v3233_1_followups",
                     "v3233_followups", "v3232_followups"):
            self.assertIn(key, data,
                            f"prior followup block dropped: {key}")


if __name__ == "__main__":
    unittest.main()
