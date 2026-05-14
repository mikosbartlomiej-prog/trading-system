"""E2E: emergency engine + remediation, deterministic + paper-only."""

import os, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
import conftest  # noqa: F401

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import emergency_engine as ee
import remediation as rm
import autonomy
import audit


ACCOUNT = {"equity": "100000", "cash": "50000", "daily_pl_pct": "-2.0"}


def pos(symbol, plpc=-0.02, side="long"):
    return {"symbol": symbol, "qty": "1", "side": side,
            "unrealized_plpc": str(plpc),
            "asset_class": "us_equity",
            "avg_entry_price": "100"}


class TestEmergencyEngineE2E(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["AUDIT_TRADING_DIR"] = self.tmp
        ee._attempts_today.clear()

    def tearDown(self):
        os.environ.pop("AUDIT_TRADING_DIR", None)

    def test_hard_loss_autoselects(self):
        targets = ee.scan_emergency_conditions(
            ACCOUNT, [pos("AAPL", plpc=-0.20)], []
        )
        self.assertEqual(len(targets), 1)
        self.assertIn("hard_loss", targets[0].reason)

    def test_no_exit_plan_autoselects(self):
        targets = ee.scan_emergency_conditions(
            ACCOUNT, [pos("AAPL", plpc=-0.05)], []
        )
        self.assertEqual(targets[0].reason, "no_exit_plan")

    def test_dry_run_writes_audit_no_real_calls(self):
        target = ee.EmergencyTarget(symbol="AAPL", reason="test")
        with mock.patch("emergency_engine.requests") as mreq:
            r = ee.execute_emergency_close(target, dry_run=True)
        self.assertTrue(r["ok"])
        mreq.delete.assert_not_called()
        records = audit.read_today(kind="trading")
        self.assertTrue(any(rec["decision_type"] == "EMERGENCY_CLOSE"
                              for rec in records))

    def test_paper_only_violation_blocks(self):
        target = ee.EmergencyTarget(symbol="AAPL", reason="test")
        with mock.patch.object(ee, "ALPACA_BASE_URL",
                                "https://api.alpaca.markets"):
            r = ee.execute_emergency_close(target, dry_run=False)
        self.assertFalse(r["ok"])
        self.assertEqual(r["blocked_by"], "paper_only")

    def test_max_attempts_prevents_loop(self):
        ee._attempts_today[ee._attempts_key("AAPL")] = ee.MAX_ATTEMPTS_PER_DAY
        r = ee.execute_emergency_close(
            ee.EmergencyTarget(symbol="AAPL", reason="test"),
            dry_run=False,
        )
        self.assertFalse(r["ok"])
        self.assertEqual(r["blocked_by"], "max_attempts")


class TestRemediationE2E(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["AUDIT_TRADING_DIR"] = self.tmp
        rm._cooldown.clear()
        ee._attempts_today.clear()

    def tearDown(self):
        os.environ.pop("AUDIT_TRADING_DIR", None)

    def test_stale_orders_trigger_cleanup(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        health = {
            "max_severity": "WARN",
            "checks": [
                {"name": "stale_orders", "severity": "WARN",
                 "stale": [{"id": "abc", "symbol": "AAPL", "age_hours": 30}]},
            ],
        }
        with mock.patch.object(rm, "requests"):
            report = rm.remediate(health, dry_run=True)
        actions = [a["action"] for a in report.actions_taken]
        self.assertIn("CANCEL_STALE_ORDERS", actions)

    def test_health_blocked_sets_block_flag(self):
        health = {
            "max_severity": "BLOCKED",
            "checks": [
                {"name": "alpaca_auth", "severity": "BLOCKED",
                 "detail": "auth fail"},
            ],
        }
        report = rm.remediate(health, dry_run=True)
        self.assertTrue(report.blocked)

    def test_cooldown_prevents_loop(self):
        action = rm.RemediationAction(
            action="CANCEL_STALE_ORDERS", subject="AAPL",
            reason="test", severity="WARN",
        )
        self.assertTrue(rm._cooldown_ok(action.action, action.subject))
        rm._stamp_cooldown(action.action, action.subject)
        self.assertFalse(rm._cooldown_ok(action.action, action.subject))


class TestNoForbiddenStatesInDecisions(unittest.TestCase):
    """Every emergency / remediation Decision must NOT include
    forbidden approval-needed wording."""

    def test_emergency_close_decision_clean(self):
        d = autonomy.make_decision(
            decision_type="EMERGENCY_CLOSE",
            decision="CLOSED",
            reason="hard loss -22%",
            actor="emergency_engine",
            affected_symbols=["AAPL"],
        )
        self.assertNotIn("approval", d.reason.lower())

    def test_remediation_actions_are_in_decision_enum(self):
        for action in ("CLEANUP_STALE_ORDERS", "RECREATE_EXIT_PLAN",
                        "BLOCK_NEW_ENTRIES", "PANIC_CLOSE_OPTIONS"):
            self.assertIn(action, autonomy.DECISION_TYPES)


if __name__ == "__main__":
    unittest.main()
