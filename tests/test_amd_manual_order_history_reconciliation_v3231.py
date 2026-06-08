"""v3.23.1 (2026-06-08) — AMD manual Order History reconciliation tests.

Operator pulled the actual Alpaca paper Order History for AMD after
v3.23 shipped, revealing:

- Open: BUY 34 @ $497.875 (filled 2026-06-05T15:39:57-04:00)
- Close: MARKET SELL 34 @ $485.02 (filled 2026-06-05T17:35:45-04:00,
  submitter_source=access_key, NO local safe_close event)
- Realized P/L: -$437.07 (-2.58%)
- 2 canceled protective orders (TP @ $558.33, SL @ $473.58)

The previous v3.23 classification
`BROKER_SIDE_CLOSED_OR_DASHBOARD_VERIFIED_NOT_OPEN` is refined into:

- v3.23.1: `EXTERNAL_API_MARKET_CLOSE_VERIFIED_FROM_DASHBOARD`
- Secondary finding:
  `MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT`

Tests pin the contract so future regressions can't silently revert
to the looser status or invent P/L data.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestReconciliationStatusEnumExtended(unittest.TestCase):
    def test_new_statuses_present(self):
        import position_reconciliation_status as p
        self.assertIn(p.DASHBOARD_ORDER_HISTORY_VERIFIED_CLOSED, p.ALL_STATUSES)
        self.assertIn(p.EXTERNAL_API_MARKET_CLOSE_VERIFIED_FROM_DASHBOARD,
                       p.ALL_STATUSES)
        # The secondary finding marker is a public string constant.
        self.assertEqual(
            p.MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT,
            "MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT",
        )


class TestClassifierAMDFromManualOrderHistory(unittest.TestCase):
    def test_market_close_via_access_key(self):
        import position_reconciliation_status as p
        r = p.classify(
            "AMD",
            local_state="armed",  # stale local state — still says ARMED
            broker_evidence="dashboard_not_open",
            has_audit_safe_close=False,  # no local safe_close
            manual_order_history_evidence=True,
            manual_order_history_close_type="market",
            submitter_source="access_key",
        )
        self.assertEqual(
            r.status, p.EXTERNAL_API_MARKET_CLOSE_VERIFIED_FROM_DASHBOARD)
        # No longer requires API follow-up — we have the close price.
        self.assertFalse(r.requires_api_followup)
        self.assertIn("MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT",
                       r.rationale)

    def test_dashboard_order_history_generic_close(self):
        # Any close type other than market-via-access_key falls into the
        # generic verified-closed bucket.
        import position_reconciliation_status as p
        r = p.classify(
            "FOO",
            local_state="armed",
            broker_evidence="dashboard_not_open",
            has_audit_safe_close=False,
            manual_order_history_evidence=True,
            manual_order_history_close_type="limit",
            submitter_source="operator_dashboard",
        )
        self.assertEqual(r.status, p.DASHBOARD_ORDER_HISTORY_VERIFIED_CLOSED)


class TestTradeReconstructionAMDFromManualOrderHistory(unittest.TestCase):
    def test_amd_pair_reconstruction(self):
        import trade_reconstruction as tr
        trade = tr.trade_from_manual_order_history(
            symbol="AMD",
            open_qty=34, open_price=497.875,
            open_ts="2026-06-05T15:39:57-04:00",
            close_qty=34, close_price=485.02,
            close_ts="2026-06-05T17:35:45-04:00",
            close_type="market",
            submitter_source="access_key",
        )
        self.assertEqual(trade.status,
                          tr.TRADE_CLOSED_WITH_PNL_MANUAL_ORDER_HISTORY)
        self.assertEqual(trade.qty, 34)
        self.assertEqual(trade.open_price, 497.875)
        self.assertEqual(trade.close_price, 485.02)
        # Realized P/L: (485.02 - 497.875) * 34 = -437.07
        self.assertAlmostEqual(trade.realized_pnl_usd, -437.07, places=2)
        # Audit-gap note must be visible in notes.
        self.assertIn("MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT",
                       trade.notes)
        # Manual sources marked explicitly.
        self.assertEqual(trade.open_source, "manual_order_history")
        self.assertEqual(trade.close_source, "manual_order_history")

    def test_no_pnl_when_prices_missing(self):
        import trade_reconstruction as tr
        trade = tr.trade_from_manual_order_history(
            symbol="X",
            open_qty=10, open_price=None,
            open_ts="t1",
            close_qty=10, close_price=None,
            close_ts="t2",
        )
        self.assertEqual(trade.status, tr.TRADE_CLOSED_PRICE_MISSING)
        self.assertIsNone(trade.realized_pnl_usd)

    def test_canceled_protective_orders_do_not_count(self):
        # The reconstruction builder takes only filled qty/price values.
        # Canceled orders are explicitly not supplied to this helper, so
        # the realized P/L is derived from the actual filled qty (34)
        # at the actual filled price ($485.02) — not from any canceled
        # limit at $558.33 or stop at $473.58.
        import trade_reconstruction as tr
        trade = tr.trade_from_manual_order_history(
            symbol="AMD",
            open_qty=34, open_price=497.875, open_ts="t1",
            close_qty=34, close_price=485.02, close_ts="t2",
            close_type="market", submitter_source="access_key",
        )
        # Sanity: canceled TP @ 558.33 would imply +$2057 — must NOT be in P/L.
        self.assertLess(trade.realized_pnl_usd, 0)
        # Canceled SL @ 473.58 would imply -$826 — must NOT be in P/L.
        self.assertGreater(trade.realized_pnl_usd, -500)


class TestManualOrderHistoryFile(unittest.TestCase):
    def test_file_exists_and_is_valid_json(self):
        path = (REPO_ROOT / "learning-loop" / "position_reconciliation"
                / "manual_order_history_AMD_2026-06-04.json")
        self.assertTrue(path.exists())
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["source"], "OPERATOR_ORDER_HISTORY_MANUAL")
        self.assertEqual(data["symbol"], "AMD")

    def test_realized_pnl_matches_arithmetic(self):
        path = (REPO_ROOT / "learning-loop" / "position_reconciliation"
                / "manual_order_history_AMD_2026-06-04.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        pair = data["trade_pair_used_for_incident_reconstruction"]
        buy_total = pair["open"]["total_amount_usd"]
        sell_total = pair["close"]["total_amount_usd"]
        self.assertAlmostEqual(data["realized_pnl_usd"],
                                sell_total - buy_total, places=2)

    def test_audit_gap_finding_present(self):
        path = (REPO_ROOT / "learning-loop" / "position_reconciliation"
                / "manual_order_history_AMD_2026-06-04.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(
            data["audit_gap_finding"]["kind"],
            "MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT",
        )

    def test_older_amd_trades_explicitly_ignored(self):
        path = (REPO_ROOT / "learning-loop" / "position_reconciliation"
                / "manual_order_history_AMD_2026-06-04.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("ignored_trade_pairs", data)


class TestNoUnsafeBehavior(unittest.TestCase):
    def test_module_does_not_place_orders(self):
        import ast
        for src_path in [
            REPO_ROOT / "shared" / "position_reconciliation_status.py",
            REPO_ROOT / "shared" / "trade_reconstruction.py",
        ]:
            src = src_path.read_text()
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = (func.id if isinstance(func, ast.Name)
                             else func.attr if isinstance(func, ast.Attribute)
                             else None)
                    if name in (
                        "place_stock_bracket", "place_crypto_order",
                        "place_simple_buy", "safe_close",
                    ):
                        self.fail(f"{src_path.name}: forbidden call {name!r}")


if __name__ == "__main__":
    unittest.main()
