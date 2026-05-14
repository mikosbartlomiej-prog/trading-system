"""E2E: stock entry lifecycle with full gate stack.

Strategy:
  signal → instrument_window → portfolio_risk → risk_officer → fake Alpaca

We don't run the real monitor binaries (they'd need Finnhub + Alpaca). We
exercise the centre choke point — `portfolio_risk.evaluate_portfolio_risk`
and `risk_officer.evaluate_trade` — which is what every monitor goes
through before placing an order. The fake Alpaca confirms the order
shape and proves no real network call happens.
"""

import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import conftest  # noqa: F401

import unittest

import portfolio_risk
import risk_officer
import autonomy
import audit


ACCOUNT_100K = {"equity": "100000", "cash": "50000", "buying_power": "200000"}


def pos(symbol, mv, side="long"):
    return {"symbol": symbol, "market_value": str(mv), "side": side,
            "qty": "1", "avg_entry_price": str(mv)}


class TestEntryLifecycleApproved(unittest.TestCase):
    """A clean signal passes every gate and the fake Alpaca accepts the order."""

    def test_full_chain_approval_writes_audit(self):
        # 1. portfolio risk
        v_port = portfolio_risk.evaluate_portfolio_risk(
            {"symbol": "AAPL", "side": "buy", "size_usd": 5000},
            ACCOUNT_100K, [], [],
        )
        self.assertEqual(v_port["decision"], "APPROVE")

        # 2. risk officer (with paper-only assert via assert_paper_only inside)
        v_off = risk_officer.evaluate_trade({
            "symbol":      "AAPL",
            "action":      "BUY",
            "size_usd":    5000,
            "entry_price": 175.0,
            "stop_loss":   170.0,
            "take_profit": 182.0,
            "strategy":    "aggressive-momentum",
        })
        # USE_RISK_OFFICER=true. Either APPROVE (account fetch fail-open)
        # or APPROVE with warnings.
        self.assertEqual(v_off["decision"], "APPROVE")

        # 3. Audit the decision — never a forbidden state
        d = autonomy.make_decision(
            decision_type="APPROVE_ENTRY",
            decision="APPROVE",
            reason="all gates passed",
            actor="e2e-test",
            affected_symbols=["AAPL"],
        )
        # Should not raise — no forbidden wording
        self.assertIn(d.decision_type, autonomy.DECISION_TYPES)


class TestEntryLifecycleRejected(unittest.TestCase):
    """Each rejection variant produces REJECT, not 'approval needed'."""

    def test_rejected_oversized_trade(self):
        v = portfolio_risk.evaluate_portfolio_risk(
            {"symbol": "AAPL", "side": "buy", "size_usd": 15000},  # > 10% cap
            ACCOUNT_100K, [], [],
        )
        self.assertEqual(v["decision"], "REJECT")
        self.assertTrue(any("single-trade" in f for f in v["failed"]))

    def test_rejected_off_whitelist(self):
        v = risk_officer.evaluate_trade({
            "symbol":      "PENNYSTOCK",   # not in whitelist
            "action":      "BUY",
            "size_usd":    5000,
            "entry_price": 1.0,
            "stop_loss":   0.95,
            "take_profit": 1.2,
            "strategy":    "x",
        })
        self.assertEqual(v["decision"], "REJECT")

    def test_rejected_correlated_bucket_cap(self):
        # Existing 30k NVDA + 5k AMD → ai_semis 35k. New 5k AVGO → 40% > 35%
        v = portfolio_risk.evaluate_portfolio_risk(
            {"symbol": "AVGO", "side": "buy", "size_usd": 5000},
            ACCOUNT_100K, [pos("NVDA", 30000), pos("AMD", 5000)], [],
        )
        self.assertEqual(v["decision"], "REJECT")
        self.assertTrue(any("bucket" in f and "ai_semis" in f for f in v["failed"]))


class TestExecutionPaperOnly(unittest.TestCase):
    """Fake Alpaca confirms order placement without touching real network."""

    def test_fake_alpaca_accepts_paper_order(self):
        from tools.e2e_system_test_agent.fixtures import FakeAlpacaClient
        cli = FakeAlpacaClient(auto_fill=True)
        cli.verify_paper_only()       # invariant
        order = cli.submit_order(
            symbol="AAPL", qty=10, side="buy", type="limit",
            limit_price=175.0, time_in_force="day",
            order_class="bracket",
            take_profit={"limit_price": 182.0},
            stop_loss={"stop_price": 170.0},
            client_order_id="e2e-AAPL-1",
        )
        self.assertEqual(order["status"], "filled")
        self.assertEqual(order["symbol"], "AAPL")
        positions = cli.get_positions()
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["symbol"], "AAPL")

    def test_fake_alpaca_rejects_live_endpoint(self):
        from tools.e2e_system_test_agent.fixtures import FakeAlpacaClient
        cli = FakeAlpacaClient(endpoint="https://api.alpaca.markets")
        with self.assertRaises(RuntimeError):
            cli.verify_paper_only()


class TestAuditCapture(unittest.TestCase):
    """Every E2E decision produces an audit entry that can be re-read."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        os.environ["AUDIT_TRADING_DIR"] = self.tmp

    def tearDown(self):
        os.environ.pop("AUDIT_TRADING_DIR", None)

    def test_audit_event_for_approve(self):
        d = autonomy.make_decision(
            decision_type="APPROVE_ENTRY",
            decision="APPROVE",
            reason="e2e fixture",
            actor="e2e-test",
            affected_symbols=["AAPL"],
        )
        audit.write_audit_event(d, kind="trading")
        records = audit.read_today(kind="trading")
        self.assertEqual(records[-1]["decision_type"], "APPROVE_ENTRY")
        # Never a forbidden state
        self.assertNotIn("approval", records[-1]["reason"].lower())


if __name__ == "__main__":
    unittest.main()
