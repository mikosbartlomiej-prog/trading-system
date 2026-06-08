"""v3.23 (2026-06-08) — Drawdown attribution + silent strategy classification tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestDrawdownAttribution(unittest.TestCase):
    def test_realized_dominant(self):
        import drawdown_attribution as da
        # Stylized: equity drop -$5000 vs baseline; realized -$4500 (within 30%)
        r = da.attribute_drawdown(
            equity_now=95000, baseline_equity=100000,
            baseline_is_static=True,
            dashboard_unrealized_pl_usd=478.0,
            reconstructed_realized_pnl_usd=-4500.0,
            api_history_available=False,
        )
        self.assertEqual(r.primary_source,
                          da.DRAWDOWN_REALIZED_FROM_CLOSED_EQUITY_TRADES)
        self.assertTrue(r.baseline_stale_flag)

    def test_unrealized_dominant(self):
        import drawdown_attribution as da
        r = da.attribute_drawdown(
            equity_now=90000, baseline_equity=100000,
            baseline_is_static=False,
            dashboard_unrealized_pl_usd=-10500.0,
            reconstructed_realized_pnl_usd=None,
            api_history_available=True,
        )
        self.assertEqual(r.primary_source,
                          da.DRAWDOWN_UNREALIZED_FROM_OPEN_POSITIONS)

    def test_baseline_stale_when_no_attribution(self):
        import drawdown_attribution as da
        r = da.attribute_drawdown(
            equity_now=90000, baseline_equity=100000,
            baseline_is_static=True,
            dashboard_unrealized_pl_usd=500.0,
            reconstructed_realized_pnl_usd=None,
            api_history_available=False,
        )
        self.assertEqual(r.primary_source,
                          da.DRAWDOWN_BASELINE_STALE_REQUIRES_OPERATOR_REVIEW)

    def test_unknown_when_missing_inputs(self):
        import drawdown_attribution as da
        r = da.attribute_drawdown(
            equity_now=None, baseline_equity=None,
            baseline_is_static=False)
        self.assertEqual(r.primary_source,
                          da.DRAWDOWN_SOURCE_UNKNOWN_REQUIRES_API_HISTORY)

    def test_invariants(self):
        import drawdown_attribution as da
        self.assertTrue(da.NEVER_RESETS_BASELINE_AUTOMATICALLY)
        self.assertTrue(da.NEVER_LOWERS_DRAWDOWN_THRESHOLD)
        self.assertTrue(da.NEVER_HIDES_REALIZED_LOSS)


class TestSilentStrategyClassification(unittest.TestCase):
    def test_truly_silent(self):
        import silent_strategy_classification as ssc
        r = ssc.classify_strategy_activity(
            "ghost-strategy",
            signals_count=0, opportunity_count=0,
            orders_submitted_count=0, orders_filled_count=0,
            safe_close_count=0, broker_side_close_count=0,
            reconstructed_closed_trades_count=0,
            unmatched_opens_count=0, unmatched_closes_count=0,
            stale_local_positions_count=0,
            days_since_last_activity=90,
        )
        self.assertEqual(r.status, ssc.NO_SIGNALS)

    def test_fills_but_no_reconstructed_trades_blocks_auto_disable(self):
        # The 2026-06-08 case: strategy has fills + safe_close events
        # but reconstructed = 0 due to FIFO bug. Must NOT auto-disable.
        import silent_strategy_classification as ssc
        r = ssc.classify_strategy_activity(
            "geo-defense",
            signals_count=10,
            opportunity_count=10,
            orders_submitted_count=8,
            orders_filled_count=8,
            safe_close_count=7,
            broker_side_close_count=1,
            reconstructed_closed_trades_count=0,  # the bug
            days_since_last_activity=64,
        )
        self.assertEqual(r.status, ssc.FILLS_BUT_NO_RECONSTRUCTED_TRADES)
        self.assertTrue(r.block_auto_disable)

    def test_signals_but_no_orders(self):
        import silent_strategy_classification as ssc
        r = ssc.classify_strategy_activity(
            "crypto-momentum",
            signals_count=5, opportunity_count=5,
            orders_submitted_count=0, orders_filled_count=0,
        )
        self.assertEqual(r.status, ssc.SIGNALS_BUT_NO_ORDERS)
        # Gate working correctly is NOT a reason to auto-disable
        self.assertFalse(r.block_auto_disable)

    def test_reconstruction_failed(self):
        import silent_strategy_classification as ssc
        r = ssc.classify_strategy_activity(
            "foo",
            signals_count=5, orders_submitted_count=5,
            orders_filled_count=5, safe_close_count=2,
            reconstructed_closed_trades_count=2,
            unmatched_opens_count=3,  # bug
            unmatched_closes_count=0,
        )
        self.assertEqual(r.status, ssc.RECONSTRUCTION_FAILED)
        self.assertTrue(r.block_auto_disable)

    def test_active_but_stale_analyzer(self):
        import silent_strategy_classification as ssc
        r = ssc.classify_strategy_activity(
            "options-momentum",
            signals_count=1, opportunity_count=1,
            orders_submitted_count=1, orders_filled_count=1,
            safe_close_count=1,
            reconstructed_closed_trades_count=1,
            stale_local_positions_count=0,
        )
        self.assertEqual(r.status, ssc.ACTIVE_BUT_ANALYZER_STALE)
        self.assertTrue(r.block_auto_disable)

    def test_invariants(self):
        import silent_strategy_classification as ssc
        self.assertTrue(ssc.NEVER_AUTO_DISABLES_STRATEGY)
        self.assertTrue(ssc.NEVER_AUTO_CLEARS_LLM_OVERRIDE_LOCK)
        self.assertTrue(ssc.RECONSTRUCTION_FAILURE_BLOCKS_AUTO_DISABLE)


if __name__ == "__main__":
    unittest.main()
