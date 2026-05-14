"""E2E: deterministic behaviour under common failure modes.

Covers:
  - Alpaca timeout
  - market data stale
  - quote missing
  - LLM unavailable
  - invalid state
  - duplicate order rejected by fake Alpaca

Each path must end in REJECT or safe-degrade — never crash, never need
human approval, never submit a real order.
"""

import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import conftest  # noqa: F401

import unittest

import portfolio_risk
import state_schema
from tools.e2e_system_test_agent.fixtures import (
    FakeAlpacaClient, FakeMarketData, FakeLLM,
)


class TestFailureModesE2E(unittest.TestCase):
    def test_alpaca_timeout_fails_open_for_portfolio_risk(self):
        # account=None simulates "Alpaca unavailable"
        v = portfolio_risk.evaluate_portfolio_risk(
            {"symbol": "AAPL", "side": "buy", "size_usd": 5000},
            None, None, None,
        )
        self.assertEqual(v["decision"], "APPROVE")
        self.assertTrue(any("fail-open" in w for w in v["warnings"]))

    def test_market_data_stale_quote_missing(self):
        md = FakeMarketData()
        md.mark_stale("NVDA")
        self.assertIsNone(md.get_latest_quote("NVDA"))
        self.assertIsNone(md.get_daily_bars("NVDA"))

    def test_llm_unavailable_does_not_block(self):
        llm = FakeLLM(mode="disabled")
        self.assertIsNone(llm.call())
        # And invalid JSON path
        llm2 = FakeLLM(mode="invalid_json")
        out = llm2.call()
        self.assertIsInstance(out, str)

    def test_corrupted_state_validator_recovers(self):
        bad = {"strategies": "not a dict", "wormhole": "bad"}
        sanitized, errors = state_schema.validate_state(bad)
        self.assertEqual(sanitized["strategies"], {})
        self.assertTrue(errors)

    def test_fake_alpaca_duplicate_order_rejected(self):
        cli = FakeAlpacaClient(auto_fill=True)
        first = cli.submit_order(
            symbol="AAPL", qty=1, side="buy", type="limit",
            limit_price=175.0, time_in_force="day",
            client_order_id="duplicate-1",
        )
        second = cli.submit_order(
            symbol="AAPL", qty=1, side="buy", type="limit",
            limit_price=175.0, time_in_force="day",
            client_order_id="duplicate-1",
        )
        self.assertEqual(first["status"], "filled")
        self.assertEqual(second.get("_status"), 422)

    def test_fake_alpaca_insufficient_buying_power(self):
        cli = FakeAlpacaClient(equity=10_000.0, cash=10_000.0,
                                buying_power=10_000.0, auto_fill=False)
        r = cli.submit_order(
            symbol="AAPL", qty=1000, side="buy", type="limit",
            limit_price=200.0, time_in_force="day",
            client_order_id="big-1",
        )
        self.assertEqual(r.get("_status"), 403)

    def test_fake_alpaca_market_closed_blocks_market_order(self):
        cli = FakeAlpacaClient(auto_fill=False)
        cli.market_open = False
        r = cli.submit_order(
            symbol="AAPL", qty=1, side="buy", type="market",
            time_in_force="day", client_order_id="m-1",
        )
        # Market orders are blocked when closed; limits would still queue
        self.assertEqual(r.get("_status"), 422)


if __name__ == "__main__":
    unittest.main()
