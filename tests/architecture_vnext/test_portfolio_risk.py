"""portfolio_risk — symbol/bucket/gross/options caps."""
import os
import unittest
from unittest import mock

import os, sys; sys.path.insert(0, os.path.dirname(__file__)); import _path  # noqa: F401

import portfolio_risk


ACCOUNT_100K = {"equity": "100000", "cash": "50000", "buying_power": "200000"}


def pos(symbol, mv, side="long"):
    return {"symbol": symbol, "market_value": mv, "side": side,
            "qty": "1", "avg_entry_price": mv}


class TestExposure(unittest.TestCase):
    def test_empty_inputs(self):
        e = portfolio_risk.compute_exposure(None, None, None)
        self.assertEqual(e["equity"], 0.0)
        self.assertEqual(e["gross_exposure_usd"], 0.0)
        self.assertEqual(e["per_symbol_exposure"], {})

    def test_single_position(self):
        e = portfolio_risk.compute_exposure(
            ACCOUNT_100K, [pos("NVDA", 25000)], []
        )
        self.assertEqual(e["equity"], 100000.0)
        self.assertEqual(e["gross_exposure_usd"], 25000.0)
        self.assertEqual(e["per_symbol_exposure"]["NVDA"], 25.0)
        # NVDA sits in both ai_semis and nasdaq_beta buckets
        self.assertEqual(e["correlated_bucket_exposure"]["ai_semis"], 25.0)
        self.assertEqual(e["correlated_bucket_exposure"]["nasdaq_beta"], 25.0)

    def test_pending_orders_counted_separately(self):
        e = portfolio_risk.compute_exposure(
            ACCOUNT_100K,
            [pos("NVDA", 10000)],
            [{"symbol": "NVDA", "qty": "10", "limit_price": "200",
              "client_order_id": "momentum-NVDA-1"}],
        )
        self.assertEqual(e["pending_exposure_usd"]["NVDA"], 2000.0)
        # Existing positions still 10000; pending tracked separately
        self.assertEqual(e["per_symbol_exposure_usd"]["NVDA"], 10000.0)

    def test_exit_orders_not_counted_as_pending(self):
        e = portfolio_risk.compute_exposure(
            ACCOUNT_100K, [pos("NVDA", 10000)],
            [{"symbol": "NVDA", "qty": "10", "limit_price": "300",
              "client_order_id": "exit-tp-NVDA-1"}],
        )
        self.assertNotIn("NVDA", e["pending_exposure_usd"])


class TestPortfolioRiskBalanced(unittest.TestCase):
    """All tests run with BALANCED_PAPER profile (default)."""

    def setUp(self):
        os.environ["RISK_PROFILE"] = "BALANCED_PAPER"

    def tearDown(self):
        os.environ.pop("RISK_PROFILE", None)

    def test_allows_safe_trade(self):
        v = portfolio_risk.evaluate_portfolio_risk(
            {"symbol": "AAPL", "side": "buy", "size_usd": 5000},
            ACCOUNT_100K, [], [],
        )
        self.assertEqual(v["decision"], "APPROVE")
        self.assertEqual(v["failed"], [])

    def test_rejects_oversized_single_trade(self):
        # BALANCED_PAPER: max_single_trade_pct=10% → 11k on 100k = REJECT
        v = portfolio_risk.evaluate_portfolio_risk(
            {"symbol": "AAPL", "side": "buy", "size_usd": 11000},
            ACCOUNT_100K, [], [],
        )
        self.assertEqual(v["decision"], "REJECT")
        self.assertTrue(any("single-trade" in f for f in v["failed"]))

    def test_rejects_symbol_concentration(self):
        # Existing AAPL = 18k, new 5k → 23k = 23% > 20% cap
        v = portfolio_risk.evaluate_portfolio_risk(
            {"symbol": "AAPL", "side": "buy", "size_usd": 5000},
            ACCOUNT_100K, [pos("AAPL", 18000)], [],
        )
        self.assertEqual(v["decision"], "REJECT")
        self.assertTrue(any("symbol-exposure" in f for f in v["failed"]))

    def test_rejects_correlated_bucket(self):
        # ai_semis cap 35%. Already 30k NVDA + 5k AMD = 35k, new 5k AVGO → 40k
        # > 35k cap (note: bucket cap is 35% of 100k = 35k)
        positions = [pos("NVDA", 30000), pos("AMD", 5000)]
        v = portfolio_risk.evaluate_portfolio_risk(
            {"symbol": "AVGO", "side": "buy", "size_usd": 5000},
            ACCOUNT_100K, positions, [],
        )
        self.assertEqual(v["decision"], "REJECT")
        self.assertTrue(any("bucket-exposure" in f and "ai_semis" in f
                            for f in v["failed"]))

    def test_rejects_options_premium_overlimit(self):
        # BALANCED_PAPER: max_options_premium_at_risk_pct=3% → 3k on 100k.
        # Existing options 2k, new 2k → 4% > 3% cap. Use OCC-shaped symbol.
        v = portfolio_risk.evaluate_portfolio_risk(
            {"symbol": "AAPL260520C00170000", "side": "buy_to_open",
             "size_usd": 2000, "asset_class": "us_option"},
            ACCOUNT_100K, [pos("NVDA260520C00500000", 2000)], [],
        )
        self.assertEqual(v["decision"], "REJECT")
        self.assertTrue(any("options-premium" in f for f in v["failed"]))

    def test_failopen_when_equity_unknown(self):
        v = portfolio_risk.evaluate_portfolio_risk(
            {"symbol": "AAPL", "side": "buy", "size_usd": 5000},
            None, None, None,
        )
        self.assertEqual(v["decision"], "APPROVE")
        self.assertTrue(any("fail-open" in w for w in v["warnings"]))


class TestPortfolioRiskSafeFree(unittest.TestCase):
    def setUp(self):
        os.environ["RISK_PROFILE"] = "SAFE_FREE"

    def tearDown(self):
        os.environ.pop("RISK_PROFILE", None)

    def test_safe_free_is_stricter(self):
        # SAFE_FREE: max_single_trade_pct=5% → 6k on 100k = REJECT
        v = portfolio_risk.evaluate_portfolio_risk(
            {"symbol": "AAPL", "side": "buy", "size_usd": 6000},
            ACCOUNT_100K, [], [],
        )
        self.assertEqual(v["decision"], "REJECT")

    def test_safe_free_cash_reserve(self):
        # SAFE_FREE: min_cash_reserve_pct=20% → trade dropping cash below 20% rejected
        v = portfolio_risk.evaluate_portfolio_risk(
            {"symbol": "AAPL", "side": "buy", "size_usd": 4000},
            {"equity": "100000", "cash": "22000"}, [], [],
        )
        # 22k - 4k = 18k = 18% < 20% → REJECT
        self.assertEqual(v["decision"], "REJECT")
        self.assertTrue(any("cash-reserve" in f for f in v["failed"]))


if __name__ == "__main__":
    unittest.main()
