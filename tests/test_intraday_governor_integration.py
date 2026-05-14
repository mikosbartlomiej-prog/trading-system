"""
Integration test: IntradayProfitGovernor gate in shared/alpaca_orders.py.

Verifies that when the governor is in DEFEND_DAY / RED_DAY_AFTER_GREEN,
new entries are rejected BEFORE Alpaca is called. Mocks out requests.post
so the test runs offline.

Scenarios covered:
  - Stock bracket entry blocked in DEFEND_DAY (no POST attempted).
  - Crypto entry blocked in RED_DAY_AFTER_GREEN.
  - Options simple-buy blocked in PROFIT_LOCK without high-score override.
  - Same options entry ALLOWED in PROFIT_LOCK with score ≥ 0.65.
  - Stock entry allowed in normal GREEN state.

Run:
    python -m unittest tests.test_intraday_governor_integration
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared"))

try:
    import requests  # noqa: F401  — alpaca_orders.py imports requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# alpaca_orders.py uses PEP 604 `X | None` annotations (Python 3.10+).
# Local Python 3.9 envs cannot import it; CI on 3.11 is the target.
PY_OK = sys.version_info >= (3, 10)


@unittest.skipUnless(REQUESTS_AVAILABLE and PY_OK,
                     "needs requests + Python ≥ 3.10; covered by CI 3.11")
class _Base(unittest.TestCase):
    """Isolate runtime_state.json + provide Alpaca credentials shim."""

    def setUp(self):
        import importlib
        self.tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump({}, self.tmp)
        self.tmp.close()
        os.environ["STATE_WRITE_ACTOR"]    = "test"
        os.environ["RUNTIME_STATE_PATH"]   = self.tmp.name
        os.environ["INTRADAY_PROTECTION_ENABLED"] = "true"
        # Ensure alpaca_orders does NOT short-circuit on missing credentials.
        os.environ["ALPACA_API_KEY"]       = "test-key"
        os.environ["ALPACA_SECRET_KEY"]    = "test-secret"
        os.environ["USE_RISK_OFFICER"]     = "false"   # skip risk-officer for unit
        # Reload everything that depends on the path.
        import runtime_state
        importlib.reload(runtime_state)
        import intraday_governor
        importlib.reload(intraday_governor)
        import alpaca_orders
        importlib.reload(alpaca_orders)
        self.ig = intraday_governor
        self.ao = alpaca_orders

    def tearDown(self):
        os.unlink(self.tmp.name)
        for k in ("RUNTIME_STATE_PATH", "INTRADAY_PROTECTION_ENABLED"):
            os.environ.pop(k, None)

    def acct(self, eq, last=100_000):
        return {"equity": eq, "last_equity": last}


class TestEntryGateBlocking(_Base):

    @patch("alpaca_orders.requests.post")
    @patch("alpaca_orders._fetch_open_orders", return_value=[])
    @patch("alpaca_orders._fetch_positions", return_value=[])
    @patch("alpaca_orders._fetch_account",
           return_value={"equity": 100_000, "last_equity": 100_000, "cash": 50_000, "buying_power": 200_000})
    @patch("alpaca_orders._portfolio_risk_gate",
           return_value=(True, [], []))
    @patch("alpaca_orders.can_trade_now", create=True,
           return_value=(True, "ok"))
    def test_stock_bracket_blocked_in_defend_day(self, _w, _pr, _a, _p, _o, mock_post):
        # Force DEFEND_DAY
        self.ig.update(self.acct(105_000))           # peak $5k
        self.ig.update(self.acct(102_500))           # 50% retrace → DEFEND_DAY
        self.assertEqual(self.ig.get_snapshot().pnl_state, self.ig.STATE_DEFEND_DAY)

        order = self.ao.place_stock_bracket(
            symbol="NVDA", side="buy", qty=10,
            entry_price=500.0, stop_loss=475.0, take_profit=560.0,
            strategy="momentum-long",
        )
        self.assertIsNone(order)
        mock_post.assert_not_called()

    @patch("alpaca_orders.requests.post")
    @patch("alpaca_orders._fetch_open_orders", return_value=[])
    @patch("alpaca_orders._fetch_positions", return_value=[])
    @patch("alpaca_orders._fetch_account",
           return_value={"equity": 100_000, "last_equity": 100_000, "cash": 50_000, "buying_power": 200_000})
    @patch("alpaca_orders._portfolio_risk_gate", return_value=(True, [], []))
    def test_crypto_blocked_in_red_after_green(self, _pr, _a, _p, _o, mock_post):
        # Force RED_DAY_AFTER_GREEN
        self.ig.update(self.acct(105_000))
        self.ig.update(self.acct(99_500))    # peak armed + cur ≤ 0 → RED
        self.assertEqual(self.ig.get_snapshot().pnl_state, self.ig.STATE_RED_DAY_AFTER_GREEN)

        order = self.ao.place_crypto_order(
            symbol="BTC/USD", side="buy", qty=0.1,
            limit_price=70000.0, strategy="crypto-momentum",
        )
        self.assertIsNone(order)
        mock_post.assert_not_called()

    @patch("alpaca_orders.requests.post")
    def test_options_blocked_in_profit_lock_low_score(self, mock_post):
        # Force PROFIT_LOCK
        self.ig.update(self.acct(105_000))
        self.ig.update(self.acct(103_200))   # ~36% retrace → PROFIT_LOCK
        self.assertEqual(self.ig.get_snapshot().pnl_state, self.ig.STATE_PROFIT_LOCK)

        order = self.ao.place_simple_buy(
            symbol="AAPL260520C00200000", qty=1, limit_price=5.00,
            strategy="options-momentum", score=0.40,
        )
        self.assertIsNone(order)
        mock_post.assert_not_called()

    @patch("alpaca_orders.requests.post")
    def test_options_allowed_in_profit_lock_high_score(self, mock_post):
        # Same PROFIT_LOCK setup, but high-score signal punches through.
        mock_post.return_value.status_code = 201
        mock_post.return_value.json.return_value = {"id": "order-abc"}
        self.ig.update(self.acct(105_000))
        self.ig.update(self.acct(103_200))
        order = self.ao.place_simple_buy(
            symbol="AAPL260520C00200000", qty=1, limit_price=5.00,
            strategy="options-momentum", score=0.80,
        )
        self.assertIsNotNone(order)
        self.assertTrue(mock_post.called)

    @patch("alpaca_orders.requests.post")
    @patch("alpaca_orders._fetch_open_orders", return_value=[])
    @patch("alpaca_orders._fetch_positions", return_value=[])
    @patch("alpaca_orders._fetch_account",
           return_value={"equity": 100_000, "last_equity": 100_000, "cash": 50_000, "buying_power": 200_000})
    @patch("alpaca_orders._portfolio_risk_gate", return_value=(True, [], []))
    def test_stock_allowed_in_green(self, _pr, _a, _p, _o, mock_post):
        mock_post.return_value.status_code = 201
        mock_post.return_value.json.return_value = {"id": "order-xyz"}
        self.ig.update(self.acct(102_000))   # GREEN
        order = self.ao.place_stock_bracket(
            symbol="NVDA", side="buy", qty=10,
            entry_price=500.0, stop_loss=475.0, take_profit=560.0,
            strategy="momentum-long",
        )
        self.assertIsNotNone(order)
        self.assertTrue(mock_post.called)

    @patch("alpaca_orders.requests.post")
    @patch("alpaca_orders._fetch_open_orders", return_value=[])
    @patch("alpaca_orders._fetch_positions", return_value=[])
    @patch("alpaca_orders._fetch_account", return_value=None)
    @patch("alpaca_orders._portfolio_risk_gate", return_value=(True, [], []))
    def test_account_unavailable_blocks_new_entry(self, _pr, _a, _p, _o, mock_post):
        # Force account-unavailable state via a None update.
        self.ig.update(account=None)
        order = self.ao.place_stock_bracket(
            symbol="NVDA", side="buy", qty=10,
            entry_price=500.0, stop_loss=475.0, take_profit=560.0,
            strategy="momentum-long",
        )
        self.assertIsNone(order)
        mock_post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
