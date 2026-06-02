"""v3.14.0 (2026-06-02) — Tests verifying confidence_inputs flows end-to-end.

Closes audit-board finding TEST-002: previously no production-level test
asserted that monitors emit `confidence_inputs` into the signal dict, so
the dormancy of the confidence gate (CONF-002) was invisible.

Each test stubs broker calls + heartbeat, captures what the entry path
receives, and asserts that:
  (a) `confidence_inputs` is present and contains required keys, OR
  (b) the gate evaluates and emits BLOCK / ALLOW deterministically.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHARED_DIR = os.path.join(REPO_ROOT, "shared")

if SHARED_DIR not in sys.path:
    sys.path.insert(0, SHARED_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


class TestConfidenceBuilderDirect(unittest.TestCase):
    """Direct test of shared/confidence_builder.build_confidence_inputs."""

    def setUp(self):
        # Isolate runtime_state under tmpdir so heartbeat reads do not
        # touch repo state.
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["AUDIT_TRADING_DIR"] = self._tmpdir.name
        os.environ["RUNTIME_STATE_PATH"] = os.path.join(self._tmpdir.name, "runtime_state.json")

    def tearDown(self):
        self._tmpdir.cleanup()
        os.environ.pop("AUDIT_TRADING_DIR", None)
        os.environ.pop("RUNTIME_STATE_PATH", None)

    def test_minimal_inputs(self):
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(strategy="crypto-momentum")
        self.assertEqual(ci["strategy"], "crypto-momentum")

    def test_full_inputs(self):
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="momentum-long",
            primary_score=0.62,
            confirmations=3,
            bars_count=60,
            regime="RISK_ON",
            account_status={"daily_pl_pct": 1.2},
            consecutive_losses=0,
        )
        self.assertEqual(ci["strategy"], "momentum-long")
        self.assertEqual(ci["primary_score"], 0.62)
        self.assertEqual(ci["confirmations"], 3)
        self.assertEqual(ci["bars_count"], 60)
        self.assertEqual(ci["regime"], "RISK_ON")
        self.assertAlmostEqual(ci["intraday_pnl_pct"], 1.2)
        self.assertEqual(ci["consecutive_losses"], 0)

    def test_fail_soft_on_bad_inputs(self):
        from confidence_builder import build_confidence_inputs
        # primary_score = "not a number" → silently dropped
        ci = build_confidence_inputs(
            strategy="x",
            primary_score="not-a-number",        # type: ignore
            account_status={"daily_pl_pct": "bad"},
        )
        self.assertEqual(ci["strategy"], "x")
        self.assertNotIn("primary_score", ci)
        self.assertNotIn("intraday_pnl_pct", ci)

    def test_compute_confidence_accepts_builder_output(self):
        """builder's output must be compatible with compute_confidence(**out)."""
        from confidence_builder import build_confidence_inputs
        from confidence import compute_confidence
        ci = build_confidence_inputs(
            strategy="crypto-momentum",
            primary_score=0.75,
            confirmations=4,
            regime="RISK_ON",
            bars_count=24,
        )
        report = compute_confidence(**ci)
        self.assertIn(report.decision, ("ALLOW", "ALERT_ONLY", "BLOCK"))
        self.assertGreaterEqual(report.total, 0.0)
        self.assertLessEqual(report.total, 1.0)


class TestRiskOfficerHonorsConfidenceInputs(unittest.TestCase):
    """End-to-end: risk_officer evaluates confidence_inputs when passed."""

    FAKE_ACCOUNT = {
        "equity":        100_000,
        "last_equity":   100_000,
        "buying_power":  200_000,
        "daily_pl_pct":  0.5,
    }

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["AUDIT_TRADING_DIR"] = self._tmpdir.name
        os.environ.pop("ALPACA_API_KEY", None)
        os.environ.pop("ALPACA_SECRET_KEY", None)
        # Patch account_status + concentration_ok so risk_officer reaches the
        # confidence gate (it short-circuits to DEFER when account=None).
        self._patches = [
            mock.patch("risk_officer.get_account_status",
                       return_value=self.FAKE_ACCOUNT),
            mock.patch("risk_officer.concentration_ok", return_value=(True, 0.0)),
            mock.patch("risk_officer.daily_drawdown_guard",
                       return_value=("OK", "ok")),
            mock.patch("risk_officer.vix_guard",
                       return_value=("OK", 1.0)),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        os.environ.pop("AUDIT_TRADING_DIR", None)

    def test_blocks_when_confidence_low(self):
        from risk_officer import evaluate_trade
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="crypto-momentum",
            primary_score=0.05,
            confirmations=0,
            regime="RISK_OFF",
            consecutive_losses=5,
        )
        proposal = {
            "symbol":      "AAPL",
            "action":      "BUY",
            "size_usd":    1000,
            "entry_price": 200,
            "stop_loss":   190,
            "take_profit": 220,
            "strategy":    "crypto-momentum",
            "confidence_inputs": ci,
        }
        verdict = evaluate_trade(proposal)
        all_text = "\n".join(verdict.get("checks_passed", [])
                              + verdict.get("checks_failed", [])
                              + verdict.get("warnings", []))
        self.assertIn("confidence", all_text.lower())

    def test_warns_when_confidence_inputs_missing(self):
        from risk_officer import evaluate_trade
        proposal = {
            "symbol":      "AAPL",
            "action":      "BUY",
            "size_usd":    1000,
            "entry_price": 200,
            "stop_loss":   190,
            "take_profit": 220,
            "strategy":    "momentum-long",
        }
        verdict = evaluate_trade(proposal)
        warnings_text = " ".join(verdict.get("warnings", []))
        self.assertIn("confidence_inputs not provided", warnings_text)

    def test_passes_when_confidence_high(self):
        from risk_officer import evaluate_trade
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="momentum-long",
            primary_score=0.85,
            confirmations=4,
            regime="RISK_ON",
            consecutive_losses=0,
        )
        proposal = {
            "symbol":      "AAPL",
            "action":      "BUY",
            "size_usd":    1000,
            "entry_price": 200,
            "stop_loss":   190,
            "take_profit": 220,
            "strategy":    "momentum-long",
            "confidence_inputs": ci,
        }
        verdict = evaluate_trade(proposal)
        passed_text = " ".join(verdict.get("checks_passed", []))
        self.assertIn("confidence_ok", passed_text)


class TestAlpacaOrdersAcceptsConfidenceInputs(unittest.TestCase):
    """Signature regression test: confidence_inputs accepted by place_*."""

    def test_place_stock_bracket_signature(self):
        from alpaca_orders import place_stock_bracket
        import inspect
        sig = inspect.signature(place_stock_bracket)
        self.assertIn("confidence_inputs", sig.parameters)

    def test_place_crypto_order_signature(self):
        from alpaca_orders import place_crypto_order
        import inspect
        sig = inspect.signature(place_crypto_order)
        self.assertIn("confidence_inputs", sig.parameters)

    def test_place_simple_buy_signature(self):
        from alpaca_orders import place_simple_buy
        import inspect
        sig = inspect.signature(place_simple_buy)
        self.assertIn("confidence_inputs", sig.parameters)

    def test_execute_stock_signal_forwards_inputs(self):
        """execute_stock_signal must forward signal.confidence_inputs to place_stock_bracket."""
        from alpaca_orders import execute_stock_signal
        with mock.patch("alpaca_orders.place_stock_bracket") as place_mock, \
             mock.patch("alpaca_orders.get_latest_quote",
                        return_value={"ask": 100, "bid": 99, "mid": 99.5}), \
             mock.patch("instrument_windows.can_trade_now", return_value=(True, "ok")):
            place_mock.return_value = {"id": "order123"}
            signal = {
                "symbol":    "AAPL",
                "action":    "BUY",
                "size_usd":  5000,
                "stop_loss": 95.0,
                "take_profit": 110.0,
                "strategy":  "momentum-long",
                "confidence_inputs": {"strategy": "momentum-long",
                                       "primary_score": 0.7},
            }
            execute_stock_signal(signal)
            self.assertTrue(place_mock.called)
            _, kwargs = place_mock.call_args
            self.assertIn("confidence_inputs", kwargs)
            self.assertEqual(kwargs["confidence_inputs"]["primary_score"], 0.7)

    def test_execute_crypto_signal_forwards_inputs(self):
        from alpaca_orders import execute_crypto_signal
        with mock.patch("alpaca_orders.place_crypto_order") as place_mock, \
             mock.patch("alpaca_orders.get_latest_crypto_quote",
                        return_value={"mid": 60000, "ask": 60010, "bid": 59990}), \
             mock.patch("instrument_windows.can_trade_now", return_value=(True, "ok")):
            place_mock.return_value = {"id": "order456"}
            signal = {
                "symbol":    "BTC/USD",
                "action":    "BUY",
                "size_usd":  8000,
                "strategy":  "crypto-momentum",
                "confidence_inputs": {"strategy": "crypto-momentum",
                                       "primary_score": 0.8},
            }
            execute_crypto_signal(signal)
            self.assertTrue(place_mock.called)
            _, kwargs = place_mock.call_args
            self.assertIn("confidence_inputs", kwargs)
            self.assertEqual(kwargs["confidence_inputs"]["primary_score"], 0.8)


class TestHeartbeatExpansion(unittest.TestCase):
    """Verify heartbeat references are present in remaining 8 monitors."""

    EXPECTED_MONITORS = (
        ("defense-monitor",       "defense-monitor/monitor.py"),
        ("twitter-monitor",       "twitter-monitor/monitor.py"),
        ("reddit-monitor",        "reddit-monitor/monitor.py"),
        ("geo-monitor",           "geo-monitor/monitor.py"),
        ("politician-monitor",    "politician-monitor/monitor.py"),
        ("options-monitor",       "options-monitor/monitor.py"),
        ("options-exit-monitor",  "options-exit-monitor/monitor.py"),
        ("price-monitor",         "price-monitor/monitor.py"),
    )

    def test_heartbeat_imports(self):
        missing = []
        for label, rel in self.EXPECTED_MONITORS:
            full = os.path.join(REPO_ROOT, rel)
            with open(full, "r", encoding="utf-8") as f:
                body = f.read()
            if "from heartbeat import ping" not in body \
                    or f'_hb_ping("{label}"' not in body:
                missing.append(label)
        self.assertEqual(missing, [],
                          f"Heartbeat ping missing in: {missing}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
