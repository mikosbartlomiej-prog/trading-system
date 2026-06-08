"""v3.23 (2026-06-08) — Trade reconstruction tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestStatusEnum(unittest.TestCase):
    def test_all_statuses(self):
        import trade_reconstruction as tr
        for s in (tr.TRADE_CLOSED_WITH_PNL, tr.TRADE_CLOSED_PRICE_MISSING,
                   tr.TRADE_BROKER_SIDE_CLOSE_INFERRED,
                   tr.TRADE_UNMATCHED_OPEN, tr.TRADE_UNMATCHED_CLOSE,
                   tr.TRADE_PARTIAL_CLOSE):
            self.assertIn(s, tr.ALL_TRADE_STATUSES)

    def test_invariants(self):
        import trade_reconstruction as tr
        self.assertTrue(tr.NEVER_PLACES_ORDERS)
        self.assertTrue(tr.NEVER_INVENTS_PRICES)
        self.assertTrue(tr.NEVER_MARKS_OPEN_AS_CLOSED_WITHOUT_EVIDENCE)


class TestFifoPairing(unittest.TestCase):
    def test_buy_and_safe_close_pair(self):
        import trade_reconstruction as tr
        opens = [{
            "symbol": "CRWD", "qty": 19, "fill_price": 690.50,
            "timestamp": "2026-06-04T13:45:00Z",
            "source": "allocator-rebalance",
        }]
        closes = [{
            "symbol": "CRWD", "qty": 19, "fill_price": 650.0,
            "timestamp": "2026-06-04T14:20:28Z",
            "source": "safe_close",
        }]
        rep = tr.reconstruct_v323(open_events=opens, close_events=closes)
        self.assertEqual(len(rep.trades), 1)
        t = rep.trades[0]
        self.assertEqual(t.status, tr.TRADE_CLOSED_WITH_PNL)
        # Realized = (650 - 690.50) * 19 = -769.5
        self.assertAlmostEqual(t.realized_pnl_usd, -769.5, places=2)
        self.assertEqual(rep.metrics["lots_paired"], 1)
        self.assertEqual(rep.metrics["closed_with_pnl"], 1)

    def test_amd_anomaly_dashboard_not_open(self):
        import trade_reconstruction as tr
        # AMD opened but no close event AND dashboard says not_open
        opens = [{
            "symbol": "AMD", "qty": 34, "fill_price": 498.51,
            "timestamp": "2026-06-04T13:45:00Z",
            "source": "allocator-rebalance",
        }]
        closes = []  # No safe_close event for AMD
        rep = tr.reconstruct_v323(
            open_events=opens, close_events=closes,
            dashboard_not_open_symbols=["AMD"],
            has_audit_safe_close={"AMD": False},
        )
        self.assertEqual(len(rep.broker_side_close_inferred), 1)
        bsi = rep.broker_side_close_inferred[0]
        self.assertEqual(bsi.status, tr.TRADE_BROKER_SIDE_CLOSE_INFERRED)
        self.assertEqual(bsi.symbol, "AMD")
        self.assertIsNone(bsi.realized_pnl_usd)
        self.assertEqual(len(rep.unmatched_opens), 0)

    def test_partial_close(self):
        import trade_reconstruction as tr
        opens = [{
            "symbol": "X", "qty": 100, "fill_price": 50,
            "timestamp": "t1", "source": "a",
        }]
        closes = [{
            "symbol": "X", "qty": 40, "fill_price": 55,
            "timestamp": "t2", "source": "safe_close",
        }]
        rep = tr.reconstruct_v323(open_events=opens, close_events=closes)
        # 40 closed, 60 remain. The first trade should be PARTIAL_CLOSE.
        self.assertEqual(rep.metrics["partial_closes"], 1)
        self.assertEqual(len(rep.unmatched_opens), 1)
        self.assertEqual(rep.unmatched_opens[0].qty, 60)

    def test_unmatched_close(self):
        import trade_reconstruction as tr
        rep = tr.reconstruct_v323(
            open_events=[],
            close_events=[{
                "symbol": "X", "qty": 10, "fill_price": 100,
                "timestamp": "t", "source": "safe_close",
            }],
        )
        self.assertEqual(rep.metrics["unmatched_closes"], 1)
        self.assertEqual(len(rep.trades), 0)

    def test_unmatched_open_remains_open(self):
        import trade_reconstruction as tr
        opens = [{"symbol": "X", "qty": 10, "fill_price": 50,
                   "timestamp": "t", "source": "a"}]
        rep = tr.reconstruct_v323(open_events=opens, close_events=[])
        self.assertEqual(len(rep.unmatched_opens), 1)
        # Without dashboard_not_open hint, must NOT be marked as closed
        self.assertEqual(len(rep.broker_side_close_inferred), 0)
        self.assertEqual(rep.metrics["unmatched_opens"], 1)

    def test_close_price_missing(self):
        import trade_reconstruction as tr
        opens = [{"symbol": "X", "qty": 10, "fill_price": None,
                   "timestamp": "t1", "source": "a"}]
        closes = [{"symbol": "X", "qty": 10, "fill_price": None,
                    "timestamp": "t2", "source": "safe_close"}]
        rep = tr.reconstruct_v323(open_events=opens, close_events=closes)
        self.assertEqual(len(rep.trades), 1)
        # No realized P&L invented when prices missing
        self.assertEqual(rep.trades[0].status, tr.TRADE_CLOSED_PRICE_MISSING)
        self.assertIsNone(rep.trades[0].realized_pnl_usd)


class TestCumulativeTradesAfterRepair(unittest.TestCase):
    def test_06_04_scenario_yields_nonzero_cumulative(self):
        """The 2026-06-04 incident: 7 BUYs all closed via safe_close.
        cumulative_trades MUST NOT be 0 after repair."""
        import trade_reconstruction as tr
        symbols_with_close = ["CRWD", "NOW", "QQQ", "SPY", "GLD", "PANW", "ORCL"]
        opens = [
            {"symbol": s, "qty": 10, "fill_price": 100,
             "timestamp": "2026-06-04T13:45:00Z", "source": "allocator-rebalance"}
            for s in symbols_with_close + ["AMD"]
        ]
        closes = [
            {"symbol": s, "qty": 10, "fill_price": 99,
             "timestamp": "2026-06-04T14:20:28Z", "source": "safe_close"}
            for s in symbols_with_close
        ]
        rep = tr.reconstruct_v323(
            open_events=opens, close_events=closes,
            dashboard_not_open_symbols=["AMD"],
            has_audit_safe_close={"AMD": False},
        )
        # Cumulative closed trades = 7 paired + 1 broker-side-inferred = 8
        total = rep.metrics["reconstructed_closed_trades_count"]
        self.assertEqual(total, 8)
        # cumulative_trades MUST NOT be 0
        self.assertGreater(total, 0)
        # Realized P&L summed
        total_realized = sum(
            t.realized_pnl_usd or 0 for t in rep.trades
            if t.realized_pnl_usd is not None
        )
        self.assertAlmostEqual(total_realized, 7 * (99 - 100) * 10, places=2)


if __name__ == "__main__":
    unittest.main()
