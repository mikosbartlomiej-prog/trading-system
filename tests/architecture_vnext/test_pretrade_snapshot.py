"""v3.10 — pre-trade snapshot tests (TTL cache + classification)."""

import os, sys, time
from unittest import mock
sys.path.insert(0, os.path.dirname(__file__))
import _path  # noqa: F401

import unittest

import pretrade_snapshot as snap_mod
from pretrade_snapshot import (
    PreTradeSnapshot, get_snapshot, classify_snapshot_for_intraday,
    clear_snapshot_cache,
)
from risk_classification import RiskVerdict


def _ok_account():
    return {
        "equity": "100000", "cash": "50000", "buying_power": "200000",
        "last_equity": "99000", "daytrade_count": "0",
        "pattern_day_trader": False, "account_blocked": False,
        "trading_blocked": False,
    }


class TestSnapshotBuild(unittest.TestCase):
    def setUp(self):
        clear_snapshot_cache()

    def test_all_data_available(self):
        with mock.patch.object(snap_mod, "_fetch_account", return_value=_ok_account()), \
             mock.patch.object(snap_mod, "_fetch_positions", return_value=[
                 {"symbol": "AAPL", "qty": "10", "market_value": "1750",
                  "asset_class": "us_equity"}
             ]), \
             mock.patch.object(snap_mod, "_fetch_open_orders", return_value=[
                 {"symbol": "AAPL", "side": "sell", "status": "open"}
             ]), \
             mock.patch.object(snap_mod, "_fetch_governor_state", return_value={
                 "pnl_state": "GREEN", "max_gross_target": 1.5,
                 "current_intraday_pnl": 200, "intraday_peak_pnl": 200,
             }):
            s = get_snapshot(force_refresh=True)

        self.assertEqual(s.equity, 100000)
        self.assertEqual(s.buying_power, 200000)
        self.assertAlmostEqual(s.daily_pl_pct, 1.01010, places=4)
        self.assertTrue(s.has_position("AAPL"))
        self.assertEqual(s.position_value("AAPL"), 1750)
        self.assertEqual(s.intraday_fsm, "GREEN")
        self.assertFalse(s.is_unavailable())
        self.assertFalse(s.is_partial())

    def test_account_unavailable_marks_critical(self):
        with mock.patch.object(snap_mod, "_fetch_account", return_value=None), \
             mock.patch.object(snap_mod, "_fetch_positions", return_value=[]), \
             mock.patch.object(snap_mod, "_fetch_open_orders", return_value=[]), \
             mock.patch.object(snap_mod, "_fetch_governor_state", return_value={}):
            s = get_snapshot(force_refresh=True)

        self.assertTrue(s.is_unavailable())
        self.assertIn("account_fetch_failed", s.errors)

    def test_partial_when_only_positions_fail(self):
        with mock.patch.object(snap_mod, "_fetch_account", return_value=_ok_account()), \
             mock.patch.object(snap_mod, "_fetch_positions", return_value=None), \
             mock.patch.object(snap_mod, "_fetch_open_orders", return_value=[]), \
             mock.patch.object(snap_mod, "_fetch_governor_state", return_value={}):
            s = get_snapshot(force_refresh=True)

        self.assertFalse(s.is_unavailable())
        self.assertTrue(s.is_partial())
        self.assertIn("positions_fetch_failed", s.errors)

    def test_paper_only_violation_blocks(self):
        # Temporarily flip base URL
        original = snap_mod.ALPACA_BASE_URL
        snap_mod.ALPACA_BASE_URL = "https://api.alpaca.markets"  # production
        try:
            s = snap_mod._build_snapshot()
            self.assertFalse(s.paper_only_ok)
        finally:
            snap_mod.ALPACA_BASE_URL = original


class TestSnapshotCache(unittest.TestCase):
    def setUp(self):
        clear_snapshot_cache()

    def test_second_call_returns_cached_no_fetch(self):
        fetch_count = {"n": 0}

        def _counting_fetch():
            fetch_count["n"] += 1
            return _ok_account()

        with mock.patch.object(snap_mod, "_fetch_account", side_effect=_counting_fetch), \
             mock.patch.object(snap_mod, "_fetch_positions", return_value=[]), \
             mock.patch.object(snap_mod, "_fetch_open_orders", return_value=[]), \
             mock.patch.object(snap_mod, "_fetch_governor_state", return_value={}):
            s1 = get_snapshot()
            s2 = get_snapshot()
            s3 = get_snapshot()
        self.assertEqual(fetch_count["n"], 1, "expected exactly 1 fetch across 3 calls (TTL cache)")
        self.assertIs(s1, s2)
        self.assertIs(s2, s3)

    def test_force_refresh_bypasses_cache(self):
        fetch_count = {"n": 0}

        def _counting_fetch():
            fetch_count["n"] += 1
            return _ok_account()

        with mock.patch.object(snap_mod, "_fetch_account", side_effect=_counting_fetch), \
             mock.patch.object(snap_mod, "_fetch_positions", return_value=[]), \
             mock.patch.object(snap_mod, "_fetch_open_orders", return_value=[]), \
             mock.patch.object(snap_mod, "_fetch_governor_state", return_value={}):
            get_snapshot()
            get_snapshot(force_refresh=True)
        self.assertEqual(fetch_count["n"], 2)


class TestClassification(unittest.TestCase):
    def test_full_data_returns_allow(self):
        s = PreTradeSnapshot(equity=100000)
        d = classify_snapshot_for_intraday(s)
        self.assertEqual(d.verdict, RiskVerdict.ALLOW)

    def test_account_unavailable_returns_defer(self):
        s = PreTradeSnapshot(account_unavailable=True, errors=["account_fetch_failed"])
        d = classify_snapshot_for_intraday(s)
        self.assertEqual(d.verdict, RiskVerdict.DEFER)
        self.assertEqual(d.retry_after_s, 60)

    def test_positions_unavailable_returns_downsize(self):
        s = PreTradeSnapshot(equity=100000, positions_unavailable=True,
                              errors=["positions_fetch_failed"])
        d = classify_snapshot_for_intraday(s)
        self.assertEqual(d.verdict, RiskVerdict.DOWNSIZE)
        self.assertEqual(d.size_multiplier, 0.5)

    def test_paper_only_violation_blocks(self):
        s = PreTradeSnapshot(paper_only_ok=False, errors=["non-paper endpoint"])
        d = classify_snapshot_for_intraday(s)
        self.assertEqual(d.verdict, RiskVerdict.BLOCK)

    def test_account_blocked_returns_block(self):
        s = PreTradeSnapshot(equity=100000, account_blocked=True)
        d = classify_snapshot_for_intraday(s)
        self.assertEqual(d.verdict, RiskVerdict.BLOCK)


if __name__ == "__main__":
    unittest.main()
