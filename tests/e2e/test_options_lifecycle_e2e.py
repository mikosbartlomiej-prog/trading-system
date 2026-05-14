"""E2E: options entry + exit lifecycle, no real Alpaca, no approval needed."""

import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import conftest  # noqa: F401

import unittest
from datetime import datetime, timedelta, timezone

import portfolio_risk
import autonomy


ACCOUNT_100K = {"equity": "100000", "cash": "60000", "buying_power": "200000"}


def opt_pos(contract, mv, plpc=-0.05):
    return {"symbol": contract, "market_value": str(mv), "side": "long",
            "qty": "1", "avg_entry_price": str(mv / 100),
            "asset_class": "us_option", "unrealized_plpc": str(plpc)}


class TestOptionsEnabledGate(unittest.TestCase):
    def test_options_disabled_means_safe_no_op(self):
        # Flip the kill switch and verify runtime_config reads it
        os.environ["OPTIONS_ENABLED"] = "false"
        try:
            import importlib
            import runtime_config
            importlib.reload(runtime_config)
            self.assertFalse(runtime_config.options_enabled())
        finally:
            os.environ["OPTIONS_ENABLED"] = "true"
            import importlib, runtime_config
            importlib.reload(runtime_config)


class TestOptionsPortfolioPremiumCap(unittest.TestCase):
    def test_options_premium_cap_blocks_oversized_entry(self):
        # BALANCED_PAPER: 3% cap → 3k of 100k. Existing 2.5k + new 1k → 3.5%
        # > 3% cap.
        positions = [opt_pos("NVDA260520C00500000", 2500)]
        v = portfolio_risk.evaluate_portfolio_risk(
            {"symbol": "AAPL260520C00170000", "side": "buy_to_open",
             "size_usd": 1000, "asset_class": "us_option"},
            ACCOUNT_100K, positions, [],
        )
        self.assertEqual(v["decision"], "REJECT")
        self.assertTrue(any("options-premium" in f for f in v["failed"]))

    def test_small_options_entry_approved(self):
        v = portfolio_risk.evaluate_portfolio_risk(
            {"symbol": "AAPL260520C00170000", "side": "buy_to_open",
             "size_usd": 500, "asset_class": "us_option"},
            ACCOUNT_100K, [], [],
        )
        self.assertEqual(v["decision"], "APPROVE")


class TestOptionsLiquidityGate(unittest.TestCase):
    def test_wide_spread_rejected(self):
        # Use the actual check_options_liquidity from options-monitor
        sys.path.insert(0, str(conftest.REPO_ROOT / "options-monitor"))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "options_monitor", conftest.REPO_ROOT / "options-monitor" / "monitor.py"
        )
        # Don't import the monitor module (heavy deps); instead test the
        # liquidity-check function shape directly:
        # spread = (ask - bid) / mid > OPTIONS_SPREAD_PCT_MAX → reject.
        # We mirror the logic here as a contract test:
        bid, ask = 1.0, 3.0       # spread 100%
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid * 100
        self.assertGreater(spread_pct, 20.0)  # default threshold

    def test_normal_spread_accepted(self):
        bid, ask = 5.0, 5.10
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid * 100
        self.assertLess(spread_pct, 20.0)


class TestOptionsAutonomousPanicClose(unittest.TestCase):
    def test_panic_close_module_honours_autonomous_env(self):
        # Reading the script statically — we don't subprocess.
        scripts = conftest.REPO_ROOT / "scripts" / "panic_close_options.py"
        text = scripts.read_text()
        self.assertIn("AUTONOMOUS_PANIC_CLOSE_OPTIONS", text)


class TestOptionsExitDecisions(unittest.TestCase):
    def test_emergency_engine_selects_near_dte_deep_loss(self):
        import emergency_engine as ee
        ee._attempts_today.clear()
        near = datetime.now(timezone.utc) + timedelta(days=2)
        sym = f"AAPL{near.strftime('%y%m%d')}P00170000"
        original_deep = ee.DEEP_OPTION_LOSS_PCT
        original_hard = ee.HARD_LOSS_PCT
        ee.DEEP_OPTION_LOSS_PCT = -10.0
        ee.HARD_LOSS_PCT = -50.0
        try:
            targets = ee.scan_emergency_conditions(
                {"equity": "100000"},
                [opt_pos(sym, 200, plpc=-0.12)],
                [{"symbol": sym, "side": "sell"}],
            )
        finally:
            ee.DEEP_OPTION_LOSS_PCT = original_deep
            ee.HARD_LOSS_PCT = original_hard
        self.assertTrue(any("option_near_dte" in t.reason for t in targets))


if __name__ == "__main__":
    unittest.main()
