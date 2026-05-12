"""
Unit tests for shared/allocator.py::execute_orders() + trace logging +
shared/notify.py allocation email helpers.

Mocks Alpaca + Gmail; no network calls. Run:
  python -m unittest tests.aggressive.test_allocator_execute
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared"))


# ─── Fixtures (mirrors test_allocator.py) ──────────────────────────────

def _account(equity=100_000, cash=20_000):
    return {
        "equity":          equity,
        "portfolio_value": equity,
        "cash":            cash,
        "buying_power":    equity * 2,
        "last_equity":     equity,
        "daily_pl_pct":    0.0,
        "account_blocked": False,
        "trading_blocked": False,
    }


def _position(symbol, market_value, qty=None, equity=100_000):
    return {
        "symbol":          symbol,
        "asset_class":     "us_equity",
        "side":            "long",
        "qty":             qty if qty is not None else max(1, int(market_value / 100)),
        "avg_entry_price": 100.0,
        "current_price":   100.0,
        "market_value":    market_value,
        "unrealized_pl":   0,
        "unrealized_plpc": 0.0,
        "pct_equity":      round(abs(market_value) / equity * 100, 2),
    }


def _scored(ticker, score=0.5):
    return {"ticker": ticker, "score": score, "tradeable": True,
              "bucket": "ai_nasdaq_semis", "reason": "test"}


# ─── execute_orders: dispatch + gates ──────────────────────────────────

class TestExecuteOrdersDispatch(unittest.TestCase):

    def setUp(self):
        from allocator import AccountAwareAllocator
        self.alloc = AccountAwareAllocator()
        # Build a plan with synthetic orders we'll inject into execute_orders
        self.alloc.trace = self.alloc.trace.__class__()  # fresh trace

    def test_auto_execute_off_returns_empty(self):
        """Default flag=false → execute_orders returns [] without calling Alpaca."""
        self.alloc.cfg["auto_execute_rebalance"] = False
        orders = [{
            "symbol": "AAPL", "action": "BUY", "asset_class": "us_equity",
            "qty_delta": 10, "current_price": 150.0, "current_value": 0,
            "target_value": 1500, "delta": 1500, "reason": "test",
        }]
        with patch("requests.post") as mock_post:
            results = self.alloc.execute_orders(orders)
            self.assertEqual(results, [])
            mock_post.assert_not_called()

    def test_force_overrides_off_flag(self):
        """force=True executes even when config flag is false."""
        self.alloc.cfg["auto_execute_rebalance"] = False
        orders = [{
            "symbol": "AAPL", "action": "EXIT", "asset_class": "us_equity",
            "qty_delta": -5, "current_price": 150.0, "current_value": 750,
            "target_value": 0, "delta": -750, "reason": "test EXIT",
        }]
        with patch("alpaca_orders._headers", return_value={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"}), \
             patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = {"id": "ord-123"}
            results = self.alloc.execute_orders(
                orders, force=True,
                market_hours_override=(True, "open"),
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["status"], "placed")
            self.assertEqual(results[0]["alpaca_order_id"], "ord-123")
            mock_post.assert_called_once()

    def test_market_closed_skips_stock_orders(self):
        """When market not open, stock orders are skipped (crypto would proceed)."""
        self.alloc.cfg["auto_execute_rebalance"] = True
        orders = [{
            "symbol": "AAPL", "action": "BUY", "asset_class": "us_equity",
            "qty_delta": 10, "current_price": 150.0, "current_value": 0,
            "target_value": 1500, "delta": 1500, "reason": "test",
        }]
        with patch("requests.post") as mock_post:
            results = self.alloc.execute_orders(
                orders, market_hours_override=(False, "pre_market"),
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["status"], "skipped")
            self.assertIn("market not open", results[0]["reason"])
            mock_post.assert_not_called()

    def test_hold_orders_are_filtered_out(self):
        """HOLD orders never reach _execute_one."""
        self.alloc.cfg["auto_execute_rebalance"] = True
        orders = [
            {"symbol": "AAPL", "action": "HOLD", "qty_delta": 0, "delta": 0},
            {"symbol": "NVDA", "action": "HOLD", "qty_delta": 0, "delta": 0},
        ]
        with patch("requests.post") as mock_post:
            results = self.alloc.execute_orders(
                orders, force=True, market_hours_override=(True, "open"),
            )
            self.assertEqual(results, [])
            mock_post.assert_not_called()

    def test_defensive_mode_blocks_buy_keeps_exit(self):
        """In defensive mode, BUY orders skipped but EXIT proceeds."""
        self.alloc.cfg["auto_execute_rebalance"] = True
        orders = [
            {"symbol": "AAPL", "action": "BUY", "asset_class": "us_equity",
             "qty_delta": 10, "current_price": 150.0, "current_value": 0,
             "target_value": 1500, "delta": 1500, "reason": "test BUY"},
            {"symbol": "TSLA", "action": "EXIT", "asset_class": "us_equity",
             "qty_delta": -3, "current_price": 200.0, "current_value": 600,
             "target_value": 0, "delta": -600, "reason": "test EXIT"},
        ]
        with patch.object(self.alloc, "_check_defensive_mode",
                            return_value={"active": True, "kill_switch_armed": True}), \
             patch("alpaca_orders._headers", return_value={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"}), \
             patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = {"id": "ord-tsla-exit"}
            results = self.alloc.execute_orders(
                orders, market_hours_override=(True, "open"),
            )
            # EXIT placed, BUY skipped
            statuses = {r["symbol"]: r["status"] for r in results}
            self.assertEqual(statuses.get("TSLA"), "placed")
            self.assertEqual(statuses.get("AAPL"), "skipped")
            self.assertIn("defensive_mode", next(r["reason"] for r in results if r["symbol"] == "AAPL"))


# ─── execute_orders: order routing ─────────────────────────────────────

class TestExecuteOrderRouting(unittest.TestCase):

    def setUp(self):
        from allocator import AccountAwareAllocator
        self.alloc = AccountAwareAllocator()
        self.alloc.cfg["auto_execute_rebalance"] = True

    def test_buy_stock_calls_place_stock_bracket(self):
        order = {
            "symbol": "NVDA", "action": "BUY", "asset_class": "us_equity",
            "qty_delta": 10, "current_price": 800.0, "current_value": 0,
            "target_value": 8000, "delta": 8000, "reason": "BUY new",
        }
        with patch("alpaca_orders.place_stock_bracket",
                    return_value={"id": "br-nvda-1"}) as mock_br:
            results = self.alloc.execute_orders(
                [order], force=True, market_hours_override=(True, "open"),
            )
            mock_br.assert_called_once()
            args, kwargs = mock_br.call_args
            self.assertEqual(args[0], "NVDA")
            self.assertEqual(args[1], "buy")
            self.assertEqual(results[0]["status"], "placed")

    def test_buy_crypto_calls_place_crypto_order(self):
        """Crypto BUY routes to place_crypto_order, not place_stock_bracket."""
        order = {
            "symbol": "BTC/USD", "action": "BUY", "asset_class": "crypto",
            "qty_delta": 0.05, "current_price": 60000.0, "current_value": 0,
            "target_value": 3000, "delta": 3000, "reason": "BUY crypto",
        }
        with patch("alpaca_orders.place_crypto_order",
                    return_value={"id": "cry-btc-1"}) as mock_cry, \
             patch("alpaca_orders.place_stock_bracket") as mock_br:
            results = self.alloc.execute_orders(
                [order], force=True,
                market_hours_override=(False, "closed"),   # crypto bypasses
            )
            mock_cry.assert_called_once()
            mock_br.assert_not_called()
            self.assertEqual(results[0]["status"], "placed")

    def test_reduce_posts_limit_sell(self):
        order = {
            "symbol": "GLD", "action": "REDUCE", "asset_class": "us_equity",
            "qty_delta": -3, "current_price": 200.0, "current_value": 1000,
            "target_value": 400, "delta": -600, "reason": "REDUCE",
        }
        with patch("alpaca_orders.get_latest_quote",
                    return_value={"bid": 199.5, "ask": 200.0, "mid": 199.75}), \
             patch("alpaca_orders._headers",
                    return_value={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"}), \
             patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = {"id": "red-gld-1"}
            results = self.alloc.execute_orders(
                [order], force=True, market_hours_override=(True, "open"),
            )
            mock_post.assert_called_once()
            payload = mock_post.call_args.kwargs["json"]
            self.assertEqual(payload["side"], "sell")
            self.assertEqual(payload["type"], "limit")
            self.assertEqual(results[0]["status"], "placed")

    def test_exit_posts_market_sell(self):
        order = {
            "symbol": "XLE", "action": "EXIT", "asset_class": "us_equity",
            "qty_delta": -5, "current_price": 90.0, "current_value": 450,
            "target_value": 0, "delta": -450, "reason": "EXIT all",
        }
        with patch("alpaca_orders._headers",
                    return_value={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"}), \
             patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = {"id": "exit-xle-1"}
            results = self.alloc.execute_orders(
                [order], force=True, market_hours_override=(True, "open"),
            )
            payload = mock_post.call_args.kwargs["json"]
            self.assertEqual(payload["side"], "sell")
            self.assertEqual(payload["type"], "market")
            self.assertEqual(results[0]["status"], "placed")
            self.assertEqual(results[0]["alpaca_order_id"], "exit-xle-1")

    def test_failed_alpaca_response_marks_failed(self):
        order = {
            "symbol": "AAPL", "action": "EXIT", "asset_class": "us_equity",
            "qty_delta": -2, "current_price": 150.0, "current_value": 300,
            "target_value": 0, "delta": -300, "reason": "EXIT",
        }
        with patch("alpaca_orders._headers",
                    return_value={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"}), \
             patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 422
            mock_post.return_value.text = "insufficient qty"
            results = self.alloc.execute_orders(
                [order], force=True, market_hours_override=(True, "open"),
            )
            self.assertEqual(results[0]["status"], "failed")
            self.assertIn("422", results[0]["reason"])


# ─── Trace logger + save_plan log file ─────────────────────────────────

class TestTraceLogger(unittest.TestCase):

    def setUp(self):
        from allocator import AccountAwareAllocator
        self.alloc = AccountAwareAllocator()

    def test_compute_daily_plan_populates_trace(self):
        plan = self.alloc.compute_daily_plan(
            account_override=_account(equity=100_000, cash=50_000),
            positions_override=[_position("AAPL", 10_000)],
            scored_universe_override=[_scored("NVDA", 0.7), _scored("AMD", 0.5)],
        )
        # Trace should have multiple "Step" markers
        step_lines = [l for l in self.alloc.trace.lines if "Step" in l]
        self.assertGreaterEqual(len(step_lines), 6,
                                  "expected at least 6 step markers, got "
                                  f"{len(step_lines)}: {step_lines}")
        # Plan should report trace size
        self.assertGreater(plan["trace_log_lines"], 10)

    def test_save_plan_writes_log_file(self):
        plan = self.alloc.compute_daily_plan(
            account_override=_account(equity=100_000, cash=50_000),
            positions_override=[],
            scored_universe_override=[_scored("NVDA", 0.7)],
        )
        with tempfile.TemporaryDirectory() as tmp:
            from allocator import _ALLOCATIONS_DIR
            # Monkey-patch the destination
            import allocator as A
            orig = A._ALLOCATIONS_DIR
            A._ALLOCATIONS_DIR = tmp
            try:
                path = self.alloc.save_plan(plan, "2026-05-12-test")
                self.assertTrue(path.endswith(".json"))
                self.assertTrue(os.path.exists(path))
                log_path = path.replace(".json", ".log")
                self.assertTrue(os.path.exists(log_path),
                                 f"log file should be written next to JSON: {log_path}")
                with open(log_path) as f:
                    content = f.read()
                self.assertIn("Step", content)
                self.assertIn("INFO", content)
            finally:
                A._ALLOCATIONS_DIR = orig


# ─── Email summary helpers ─────────────────────────────────────────────

class TestNotifyAllocation(unittest.TestCase):

    def test_notify_allocation_plan_builds_subject(self):
        from notify import notify_allocation_plan
        plan = {
            "date": "2026-05-12",
            "account_equity": 100_000,
            "cash": 20_000,
            "market_regime": "NEUTRAL",
            "regime_source": "auto",
            "invested_ratio_before": 0.80,
            "invested_ratio_after_target": 0.95,
            "config": {"auto_execute": False},
            "defensive_mode_active": False,
            "kill_switch_armed": False,
            "allocation_reason": "regime=NEUTRAL | primary_picks=3(54%)",
            "target_weights": {"NVDA": 0.18, "AAPL": 0.18, "SPY": 0.10},
            "rebalance_orders": [
                {"symbol": "NVDA", "action": "BUY",  "delta": 10000, "reason": "new"},
                {"symbol": "GLD",  "action": "HOLD", "delta": 100,   "reason": "below min"},
            ],
            "risk_checks": {"n_orders": 1, "n_hold": 1, "passed": [], "failed": []},
        }
        with patch("notify.send_email", return_value=True) as mock_send:
            ok = notify_allocation_plan(plan)
            self.assertTrue(ok)
            subject = mock_send.call_args[0][0]
            self.assertIn("allocator PLAN", subject)
            self.assertIn("NEUTRAL", subject)
            body = mock_send.call_args[0][1]
            self.assertIn("NVDA", body)
            self.assertIn("BUY", body)
            self.assertIn("auto_execute_rebalance", body.lower() if "auto_execute_rebalance" in body.lower() else body)

    def test_notify_allocation_execution_counts(self):
        from notify import notify_allocation_execution
        results = [
            {"symbol": "NVDA", "action": "BUY",  "status": "placed",  "reason": "ok",  "alpaca_order_id": "id1"},
            {"symbol": "GLD",  "action": "EXIT", "status": "skipped", "reason": "qty zero"},
            {"symbol": "TSLA", "action": "BUY",  "status": "failed",  "reason": "422 rejected"},
        ]
        with patch("notify.send_email", return_value=True) as mock_send:
            ok = notify_allocation_execution("2026-05-12", results)
            self.assertTrue(ok)
            subject = mock_send.call_args[0][0]
            self.assertIn("1 placed", subject)
            self.assertIn("1 skipped", subject)
            self.assertIn("1 failed", subject)
            body = mock_send.call_args[0][1]
            for sym in ("NVDA", "GLD", "TSLA"):
                self.assertIn(sym, body)


# ─── execute_allocation_plan.py CLI ────────────────────────────────────

class TestExecutorScript(unittest.TestCase):
    """Test the standalone morning executor script."""

    def setUp(self):
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

    def test_missing_plan_returns_exit_code_2(self):
        from execute_allocation_plan import main
        with tempfile.TemporaryDirectory() as tmp:
            import execute_allocation_plan as M
            orig = M._ALLOCATIONS_DIR
            M._ALLOCATIONS_DIR = tmp
            try:
                # Pass non-existent date
                old_argv = sys.argv
                sys.argv = ["execute_allocation_plan.py", "--date", "1999-01-01"]
                rc = main()
                self.assertEqual(rc, 2)
            finally:
                sys.argv = old_argv
                M._ALLOCATIONS_DIR = orig

    def test_dry_run_does_not_call_alpaca(self):
        from execute_allocation_plan import main
        with tempfile.TemporaryDirectory() as tmp:
            import execute_allocation_plan as M
            orig = M._ALLOCATIONS_DIR
            M._ALLOCATIONS_DIR = tmp
            try:
                # Seed a plan file
                plan = {
                    "date": "2026-05-12-dryrun",
                    "rebalance_orders": [
                        {"symbol": "AAPL", "action": "BUY", "asset_class": "us_equity",
                         "qty_delta": 5, "current_price": 150.0, "delta": 750,
                         "current_value": 0, "target_value": 750, "reason": "test"},
                    ],
                }
                with open(os.path.join(tmp, "2026-05-12-dryrun.json"), "w") as f:
                    json.dump(plan, f)
                old_argv = sys.argv
                sys.argv = ["execute_allocation_plan.py",
                              "--date", "2026-05-12-dryrun", "--dry-run"]
                with patch("requests.post") as mock_post:
                    rc = main()
                    self.assertEqual(rc, 0)
                    mock_post.assert_not_called()
                sys.argv = old_argv
            finally:
                M._ALLOCATIONS_DIR = orig


if __name__ == "__main__":
    unittest.main()
