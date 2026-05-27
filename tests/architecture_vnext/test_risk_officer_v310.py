"""v3.10 — risk_officer DEFER on Alpaca account outage (Phase D)."""

import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import _path  # noqa: F401

import unittest
from unittest import mock

import risk_officer


PROPOSAL_OK = {
    "symbol":      "AAPL",
    "action":      "BUY",
    "size_usd":    10000,
    "entry_price": 200.0,
    "stop_loss":   190.0,
    "take_profit": 224.0,
    "strategy":    "test",
}


class TestRiskOfficerVerdictTaxonomy(unittest.TestCase):

    def setUp(self):
        # Force USE_OFFICER=true if module checks env at import time
        os.environ["USE_RISK_OFFICER"] = "true"

    def test_account_unavailable_returns_defer(self):
        """v3.10 PHASE D — Alpaca account fetch fail must DEFER, not fail-open."""
        with mock.patch("risk_officer.get_account_status", return_value=None), \
             mock.patch("risk_officer.vix_guard", return_value=("OK", "vix ok")):
            res = risk_officer.evaluate_trade(PROPOSAL_OK)
        self.assertEqual(res["decision"], "REJECT")
        self.assertEqual(res["verdict"], "DEFER")
        self.assertIn("DEFER", res["rationale"])
        self.assertEqual(res["retry_after_s"], 60)

    def test_full_approve_has_verdict_allow(self):
        ok_account = {
            "equity": "100000", "buying_power": "200000",
            "last_equity": "100000", "daytrade_count": "0",
            "pattern_day_trader": False,
        }
        with mock.patch("risk_officer.get_account_status", return_value=ok_account), \
             mock.patch("risk_officer.vix_guard", return_value=("OK", "vix ok")), \
             mock.patch("risk_officer.concentration_ok", return_value=(True, 10.0)), \
             mock.patch("risk_officer.daily_drawdown_guard", return_value=("OK", "ok")):
            res = risk_officer.evaluate_trade(PROPOSAL_OK)
        self.assertEqual(res["decision"], "APPROVE")
        self.assertEqual(res["verdict"], "ALLOW")

    def test_off_whitelist_is_block(self):
        # symbol not on whitelist — must BLOCK even with account available
        ok_account = {
            "equity": "100000", "buying_power": "200000",
            "last_equity": "100000", "daytrade_count": "0",
            "pattern_day_trader": False,
        }
        bad = dict(PROPOSAL_OK)
        bad["symbol"] = "XYZNOTREAL"
        with mock.patch("risk_officer.get_account_status", return_value=ok_account), \
             mock.patch("risk_officer.vix_guard", return_value=("OK", "vix ok")), \
             mock.patch("risk_officer.concentration_ok", return_value=(True, 10.0)), \
             mock.patch("risk_officer.daily_drawdown_guard", return_value=("OK", "ok")):
            res = risk_officer.evaluate_trade(bad)
        self.assertEqual(res["decision"], "REJECT")
        self.assertEqual(res["verdict"], "BLOCK")
        self.assertIn("BLOCK", res["rationale"])


if __name__ == "__main__":
    unittest.main()
