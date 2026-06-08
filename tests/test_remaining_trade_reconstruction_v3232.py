"""v3.23.2 (2026-06-08) — Remaining 7-symbol trade reconstruction tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


SEVEN_SYMBOLS = ["CRWD", "NOW", "QQQ", "SPY", "GLD", "PANW", "ORCL"]


class TestPlaceholderFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = (REPO_ROOT / "learning-loop" / "position_reconciliation"
                     / "manual_order_history_remaining_2026-06-04.json")

    def test_file_exists(self):
        self.assertTrue(self.path.exists())

    def test_is_valid_json(self):
        with open(self.path, encoding="utf-8") as f:
            self.data = json.load(f)
        self.assertEqual(self.data["source"], "OPERATOR_ORDER_HISTORY_MANUAL")

    def test_has_seven_entries(self):
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        symbols_in_file = [e["symbol"] for e in data["symbols"]]
        for s in SEVEN_SYMBOLS:
            self.assertIn(s, symbols_in_file)
        self.assertEqual(len(data["symbols"]), 7)

    def test_all_placeholders_require_extraction(self):
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        for entry in data["symbols"]:
            self.assertEqual(entry["data_quality"],
                              "REQUIRES_OPERATOR_EXTRACTION",
                              f"{entry['symbol']} should be placeholder")
            # No invented prices.
            self.assertIsNone(entry["open_avg_fill_price"])
            self.assertIsNone(entry["close_avg_fill_price"])


class TestOperatorChecklist(unittest.TestCase):
    def test_doc_exists(self):
        path = (REPO_ROOT / "docs"
                / "OPERATOR_ORDER_HISTORY_EXTRACTION_CHECKLIST.md")
        self.assertTrue(path.exists())

    def test_lists_all_seven_symbols(self):
        path = (REPO_ROOT / "docs"
                / "OPERATOR_ORDER_HISTORY_EXTRACTION_CHECKLIST.md")
        text = path.read_text()
        for s in SEVEN_SYMBOLS:
            self.assertIn(s, text)

    def test_does_not_request_secrets(self):
        path = (REPO_ROOT / "docs"
                / "OPERATOR_ORDER_HISTORY_EXTRACTION_CHECKLIST.md")
        text = path.read_text().lower()
        # Must explicitly disclaim asking for credentials.
        # (Markdown bold around "not" gives "**not** asking", so check
        # for the disclaiming phrase tolerant of markdown markers.)
        text_normalized = text.replace("**", "")
        self.assertIn("not asking the operator to provide api keys",
                       text_normalized)


class TestDrawdownAttributionPartial(unittest.TestCase):
    def test_status_constants_added(self):
        import drawdown_attribution as da
        for s in (da.DRAWDOWN_ATTRIBUTION_COMPLETE,
                   da.DRAWDOWN_ATTRIBUTION_PARTIAL,
                   da.DRAWDOWN_ATTRIBUTION_REQUIRES_ORDER_HISTORY,
                   da.DRAWDOWN_ATTRIBUTION_CONFLICT):
            self.assertIn(s, da.ALL_DRAWDOWN_SOURCES)

    def test_partial_when_amd_known_and_seven_unknown(self):
        import drawdown_attribution as da
        r = da.compute_partial_attribution(
            known_realized_pnl_usd=-437.07,
            known_symbols=["AMD"],
            unknown_symbols=SEVEN_SYMBOLS,
            reported_drawdown_usd=-5741.0,
            baseline_static=True,
        )
        self.assertEqual(r["status"], da.DRAWDOWN_ATTRIBUTION_PARTIAL)
        self.assertEqual(r["unknown_symbols_count"], 7)
        self.assertTrue(r["residual_pending_operator_extraction"])
        self.assertAlmostEqual(r["known_realized_pnl_usd"], -437.07, places=2)

    def test_requires_order_history_when_nothing_known(self):
        import drawdown_attribution as da
        r = da.compute_partial_attribution(
            known_realized_pnl_usd=None,
            known_symbols=[],
            unknown_symbols=SEVEN_SYMBOLS + ["AMD"],
            reported_drawdown_usd=-5741.0,
        )
        self.assertEqual(r["status"],
                          da.DRAWDOWN_ATTRIBUTION_REQUIRES_ORDER_HISTORY)

    def test_complete_when_all_known(self):
        import drawdown_attribution as da
        r = da.compute_partial_attribution(
            known_realized_pnl_usd=-5000.0,
            known_symbols=SEVEN_SYMBOLS + ["AMD"],
            unknown_symbols=[],
            reported_drawdown_usd=-5500.0,
        )
        self.assertEqual(r["status"], da.DRAWDOWN_ATTRIBUTION_COMPLETE)

    def test_conflict_when_realized_diverges_from_drop(self):
        import drawdown_attribution as da
        # known PnL is +1000 but drawdown is -5000 → CONFLICT
        r = da.compute_partial_attribution(
            known_realized_pnl_usd=1000.0,
            known_symbols=["AMD"],
            unknown_symbols=[],
            reported_drawdown_usd=-5000.0,
        )
        self.assertEqual(r["status"], da.DRAWDOWN_ATTRIBUTION_CONFLICT)


class TestTradeReconstructionInvariants(unittest.TestCase):
    def test_missing_close_price_yields_price_missing(self):
        import trade_reconstruction as tr
        trade = tr.trade_from_manual_order_history(
            symbol="CRWD",
            open_qty=19, open_price=690.50,
            open_ts="2026-06-04T13:45:00-04:00",
            close_qty=19, close_price=None,
            close_ts="2026-06-04T14:20:28-04:00",
        )
        self.assertEqual(trade.status, tr.TRADE_CLOSED_PRICE_MISSING)
        self.assertIsNone(trade.realized_pnl_usd)

    def test_canceled_orders_excluded_from_pnl(self):
        # Canceled TP/SL data is NEVER passed to trade_from_manual_order_history;
        # the helper takes only fill prices. Confirm with a synthetic trade.
        import trade_reconstruction as tr
        trade = tr.trade_from_manual_order_history(
            symbol="ORCL",
            open_qty=58, open_price=225.57,
            open_ts="t1",
            close_qty=58, close_price=220.0,  # the actual fill
            close_ts="t2",
            close_type="market",
            submitter_source="access_key",
        )
        # If canceled TP @ $250 had been counted, P/L would be positive.
        self.assertLess(trade.realized_pnl_usd, 0)


if __name__ == "__main__":
    unittest.main()
