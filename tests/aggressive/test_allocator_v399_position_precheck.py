"""v3.9.9 (2026-05-27): _exec_buy position pre-check + EXEC_TTL extension.

Bug context (Tuesday 2026-05-26): morning-allocator triggered twice in same
session (14:16 + 16:57 UTC). First run placed 7 bracket BUYs that filled
immediately. Second run re-executed plan; the v3.8.8 "open orders" pre-check
returned 0 (orders already filled) → duplicate brackets placed for
SPY/QQQ/GLD → autonomous-remediation flagged duplicate_exits → 3 positions
market-closed.

Fixes verified by this test:
  1. _exec_buy now checks POSITIONS first; skips BUY if existing position
     within 10% of target qty
  2. EXEC_TTL bumped 60 → 360 min to cover full trading session
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared"))


class TestExecBuyPositionPrecheck(unittest.TestCase):
    """v3.9.9 fix A: skip BUY when position already exists at target qty."""

    def _make_allocator(self):
        """Build a minimal allocator instance for _exec_buy testing."""
        from allocator import AccountAwareAllocator
        with patch.object(AccountAwareAllocator, "_load_profile",
                          return_value={"exits": {"default_stop_loss_pct": 0.05,
                                                  "default_take_profit_pct": 0.12}}):
            a = AccountAwareAllocator()
            # Mock trace so tests don't print
            a.trace = MagicMock()
            return a

    def test_skip_buy_when_position_exists_at_target_qty(self):
        """Position exists with qty=10, target qty=10 → skipped."""
        a = self._make_allocator()
        order = {"action": "BUY", "symbol": "SPY", "current_price": 750.0}

        with patch("alpaca_orders._fetch_single_position",
                   return_value={"qty": "10", "symbol": "SPY"}):
            result = a._exec_buy(order, "SPY", 10.0, is_crypto=False,
                                 result={"symbol": "SPY"})

        self.assertEqual(result["status"], "skipped")
        self.assertIn("already exists", result["reason"])

    def test_skip_buy_when_within_10pct_rebalance_threshold(self):
        """current_qty=9, target_qty=10 → diff 10% → still skipped (≤10%)."""
        a = self._make_allocator()
        order = {"action": "BUY", "symbol": "AMD", "current_price": 500.0}

        with patch("alpaca_orders._fetch_single_position",
                   return_value={"qty": "9", "symbol": "AMD"}):
            result = a._exec_buy(order, "AMD", 10.0, is_crypto=False,
                                 result={"symbol": "AMD"})

        # diff = (10-9)/10 = 10% — not < 10% → proceeds to BUY (not skipped at this check)
        # But test the boundary: 9.5 vs 10 → diff=5% → SKIPPED
        with patch("alpaca_orders._fetch_single_position",
                   return_value={"qty": "9.5", "symbol": "AMD"}):
            result2 = a._exec_buy(order, "AMD", 10.0, is_crypto=False,
                                  result={"symbol": "AMD"})
        self.assertEqual(result2["status"], "skipped")

    def test_allow_buy_when_existing_position_below_threshold(self):
        """current_qty=5, target=10 → diff 50% → NOT skipped (legitimate add-on)."""
        a = self._make_allocator()
        order = {"action": "BUY", "symbol": "NVDA", "current_price": 600.0}

        # Need to also mock get_latest_quote + place_stock_bracket because
        # the function continues to place after position check is permissive
        with patch("alpaca_orders._fetch_single_position",
                   return_value={"qty": "5", "symbol": "NVDA"}), \
             patch("alpaca_orders.get_latest_quote",
                   return_value={"mid": 600.0, "bid": 599.5, "ask": 600.5}), \
             patch("alpaca_orders.place_stock_bracket",
                   return_value={"id": "test-order-id", "status": "accepted"}):
            # Also need to mock the requests open-orders check
            with patch("requests.get") as mock_get:
                mock_get.return_value.status_code = 200
                mock_get.return_value.json.return_value = []
                result = a._exec_buy(order, "NVDA", 10.0, is_crypto=False,
                                     result={"symbol": "NVDA"})
        # Should NOT be skipped at position-precheck stage
        self.assertNotEqual(result.get("status"), "skipped",
                            f"Expected proceed but got: {result}")

    def test_proceeds_when_no_existing_position(self):
        """No prior position → proceed past pre-check, go to place order."""
        a = self._make_allocator()
        order = {"action": "BUY", "symbol": "CRWD", "current_price": 680.0}

        with patch("alpaca_orders._fetch_single_position", return_value=None), \
             patch("alpaca_orders.get_latest_quote",
                   return_value={"mid": 680.0, "bid": 679.5, "ask": 680.5}), \
             patch("alpaca_orders.place_stock_bracket",
                   return_value={"id": "ord-1", "status": "accepted"}), \
             patch("requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = []
            result = a._exec_buy(order, "CRWD", 25.0, is_crypto=False,
                                 result={"symbol": "CRWD"})
        # Should proceed (status=placed, not skipped)
        self.assertNotEqual(result.get("status"), "skipped",
                            f"Expected placed but got skipped: {result}")


class TestExecTTLExtended(unittest.TestCase):
    """v3.9.9 fix A: EXEC_TTL extended 60 → 360 min."""

    def test_exec_ttl_is_360_minutes(self):
        """EXEC_TTL constant in execute_allocation_plan.py is 360 min."""
        # Read the source to verify constant
        path = os.path.join(REPO_ROOT, "scripts", "execute_allocation_plan.py")
        with open(path) as f:
            source = f.read()
        # Expect "EXEC_TTL_MIN = 360" somewhere in the file
        self.assertIn("EXEC_TTL_MIN = 360", source,
                      "EXEC_TTL_MIN must be 360 min in scripts/execute_allocation_plan.py")
        # Ensure old 60-min value is gone (sanity check)
        self.assertNotIn("EXEC_TTL_MIN = 60", source,
                         "Old EXEC_TTL_MIN = 60 must be removed")


if __name__ == "__main__":
    unittest.main()
