"""remediation — list_actions + remediate cooldown + dry-run."""
import os
import sys
import tempfile
import unittest
from unittest import mock

import os, sys; sys.path.insert(0, os.path.dirname(__file__)); import _path  # noqa: F401

import remediation


class TestListActions(unittest.TestCase):
    def test_stale_orders_action(self):
        health = {
            "max_severity": "WARN",
            "checks": [
                {"name": "stale_orders", "severity": "WARN",
                 "stale": [{"id": "abc", "symbol": "AAPL", "age_hours": 28}]},
            ],
        }
        actions = remediation.list_actions(health)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, "CANCEL_STALE_ORDERS")
        self.assertEqual(actions[0].subject, "AAPL")

    def test_missing_exit_action(self):
        health = {
            "max_severity": "WARN",
            "checks": [
                {"name": "positions_have_exit", "severity": "WARN",
                 "missing": ["NVDA"]},
            ],
        }
        actions = remediation.list_actions(health)
        self.assertEqual(actions[0].action, "RECREATE_EXIT_PLAN")
        self.assertEqual(actions[0].subject, "NVDA")

    def test_duplicate_exits_cleanup(self):
        health = {
            "max_severity": "WARN",
            "checks": [
                {"name": "duplicate_exits", "severity": "WARN",
                 "duplicates": [("AAPL", "sell", 2)]},
            ],
        }
        actions = remediation.list_actions(health)
        self.assertTrue(any(a.action == "CANCEL_STALE_ORDERS"
                             and a.metadata.get("keep_one") for a in actions))

    def test_blocked_severity_produces_block_action(self):
        health = {
            "max_severity": "BLOCKED",
            "checks": [
                {"name": "alpaca_auth", "severity": "BLOCKED",
                 "detail": "auth fail"},
            ],
        }
        actions = remediation.list_actions(health)
        self.assertTrue(any(a.action == "BLOCK_NEW_ENTRIES" for a in actions))

    def test_options_blocked_triggers_panic(self):
        health = {
            "max_severity": "BLOCKED",
            "checks": [
                {"name": "options_safety", "severity": "BLOCKED",
                 "detail": "premium-at-risk 6% > 3%"},
            ],
        }
        actions = remediation.list_actions(health)
        self.assertTrue(any(a.action == "PANIC_CLOSE_OPTIONS" for a in actions))


class TestRemediateDryRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        os.environ["AUDIT_TRADING_DIR"] = self._tmp
        remediation._cooldown.clear()

    def tearDown(self):
        os.environ.pop("AUDIT_TRADING_DIR", None)

    def test_dry_run_does_not_call_alpaca(self):
        health = {
            "max_severity": "WARN",
            "checks": [
                {"name": "stale_orders", "severity": "WARN",
                 "stale": [{"id": "abc", "symbol": "AAPL", "age_hours": 30}]},
            ],
        }
        with mock.patch.object(remediation, "requests") as mreq:
            report = remediation.remediate(health, dry_run=True)
        mreq.delete.assert_not_called()
        self.assertEqual(len(report.actions_taken), 1)
        self.assertTrue(report.actions_taken[0]["dry_run"])

    def test_block_new_entries_sets_flag(self):
        health = {
            "max_severity": "BLOCKED",
            "checks": [
                {"name": "alpaca_auth", "severity": "BLOCKED",
                 "detail": "auth fail"},
            ],
        }
        report = remediation.remediate(health, dry_run=True)
        self.assertTrue(report.blocked)
        self.assertTrue(report.block_reasons)


class TestCooldown(unittest.TestCase):
    def setUp(self):
        remediation._cooldown.clear()

    def test_cooldown_blocks_repeat(self):
        action = remediation.RemediationAction(
            action="CANCEL_STALE_ORDERS", subject="AAPL",
            reason="test", severity="WARN",
        )
        # First call: cooldown_ok is True
        self.assertTrue(remediation._cooldown_ok(action.action, action.subject))
        remediation._stamp_cooldown(action.action, action.subject)
        # Second call: cooldown_ok is False
        self.assertFalse(remediation._cooldown_ok(action.action, action.subject))


if __name__ == "__main__":
    unittest.main()
