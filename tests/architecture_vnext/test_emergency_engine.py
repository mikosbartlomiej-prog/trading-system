"""emergency_engine — scan + execute, paper-only, max attempts."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import os, sys; sys.path.insert(0, os.path.dirname(__file__)); import _path  # noqa: F401

import emergency_engine as ee
import autonomy


ACCOUNT = {"equity": "100000", "cash": "50000", "daily_pl_pct": "-2.0"}


def pos(symbol, qty=1, plpc=-0.02, side="long"):
    return {"symbol": symbol, "qty": str(qty), "side": side,
            "unrealized_plpc": str(plpc), "asset_class":
            "us_option" if len(symbol) > 7 else "us_equity",
            "avg_entry_price": "100"}


class TestScan(unittest.TestCase):
    def setUp(self):
        # Audit writes are temp-dirred to keep CI clean.
        self._tmp = tempfile.mkdtemp()
        os.environ["AUDIT_TRADING_DIR"] = self._tmp
        # Reset per-day attempt counters between tests
        ee._attempts_today.clear()

    def tearDown(self):
        os.environ.pop("AUDIT_TRADING_DIR", None)

    def test_hard_loss_selects_target(self):
        targets = ee.scan_emergency_conditions(
            ACCOUNT, [pos("AAPL", plpc=-0.20)], []
        )
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].symbol, "AAPL")
        self.assertIn("hard_loss", targets[0].reason)

    def test_no_exit_plan_selected(self):
        targets = ee.scan_emergency_conditions(
            ACCOUNT, [pos("AAPL", plpc=-0.05)], []
        )
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].reason, "no_exit_plan")

    def test_position_with_exit_plan_skipped(self):
        targets = ee.scan_emergency_conditions(
            ACCOUNT, [pos("AAPL", plpc=-0.05)],
            [{"symbol": "AAPL", "side": "sell"}],
        )
        self.assertEqual(targets, [])

    def test_duplicate_exit_orders_selected(self):
        targets = ee.scan_emergency_conditions(
            ACCOUNT, [pos("AAPL", plpc=-0.05)],
            [{"symbol": "AAPL", "side": "sell"},
             {"symbol": "AAPL", "side": "sell"}],
        )
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].reason, "duplicate_exits")

    def test_stale_exit_order_selected(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        targets = ee.scan_emergency_conditions(
            ACCOUNT, [pos("AAPL", plpc=-0.05)],
            [{"symbol": "AAPL", "side": "sell", "submitted_at": old}],
        )
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].reason, "stale_exit_order")

    def test_near_dte_deep_option_loss(self):
        # OCC: yymmdd starts after the alpha root. Use a near-DTE date.
        # plpc -0.45 = -45% which BEATS hard_loss check first (priority order
        # is: hard_loss → option_near_dte → no_exit_plan). To exercise the
        # near-DTE branch we use a loss slightly below the hard_loss cutoff
        # (-15%) but still meeting DEEP_OPTION_LOSS_PCT default (-40%).
        # We temporarily lower DEEP_OPTION_LOSS so loss -12% qualifies.
        near = datetime.now(timezone.utc) + timedelta(days=2)
        sym = f"AAPL{near.strftime('%y%m%d')}C00170000"
        original = ee.DEEP_OPTION_LOSS_PCT
        ee.DEEP_OPTION_LOSS_PCT = -10.0
        ee.HARD_LOSS_PCT_ORIG = ee.HARD_LOSS_PCT
        ee.HARD_LOSS_PCT = -50.0   # raise hard-loss bar so it doesn't trip first
        try:
            targets = ee.scan_emergency_conditions(
                ACCOUNT, [pos(sym, plpc=-0.12)],
                [{"symbol": sym, "side": "sell"}],
            )
        finally:
            ee.DEEP_OPTION_LOSS_PCT = original
            ee.HARD_LOSS_PCT = ee.HARD_LOSS_PCT_ORIG
        self.assertTrue(any("option_near_dte" in t.reason for t in targets))


class TestPaperOnlyExecution(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        os.environ["AUDIT_TRADING_DIR"] = self._tmp
        ee._attempts_today.clear()

    def tearDown(self):
        os.environ.pop("AUDIT_TRADING_DIR", None)

    def test_dry_run_writes_audit_no_alpaca(self):
        tgt = ee.EmergencyTarget(symbol="AAPL", reason="test")
        with mock.patch("emergency_engine.requests") as mreq:
            r = ee.execute_emergency_close(tgt, dry_run=True)
        self.assertTrue(r["ok"])
        self.assertTrue(r["dry_run"])
        mreq.delete.assert_not_called()

    def test_paper_only_violation_blocks(self):
        tgt = ee.EmergencyTarget(symbol="AAPL", reason="test")
        with mock.patch.object(ee, "ALPACA_BASE_URL",
                                "https://api.alpaca.markets"):
            r = ee.execute_emergency_close(tgt, dry_run=False)
        self.assertFalse(r["ok"])
        self.assertEqual(r["blocked_by"], "paper_only")

    def test_max_attempts_blocks_third_run(self):
        tgt = ee.EmergencyTarget(symbol="AAPL", reason="test")
        ee._attempts_today[ee._attempts_key("AAPL")] = ee.MAX_ATTEMPTS_PER_DAY
        r = ee.execute_emergency_close(tgt, dry_run=False)
        self.assertFalse(r["ok"])
        self.assertEqual(r["blocked_by"], "max_attempts")


if __name__ == "__main__":
    unittest.main()
