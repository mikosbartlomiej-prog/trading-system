"""patch_validator — auto-merge / PR-only / reject / forbidden."""
import os
import sys
import unittest

import os, sys; sys.path.insert(0, os.path.dirname(__file__)); import _path  # noqa: F401

import patch_validator as pv


def diff(touched: str, body_added: str = "", body_removed: str = "") -> str:
    """Build a minimal unified diff fixture."""
    lines = [
        f"diff --git a/{touched} b/{touched}",
        f"index 0000000..1111111 100644",
        f"--- a/{touched}",
        f"+++ b/{touched}",
        "@@ -1,1 +1,2 @@",
    ]
    if body_added:
        for L in body_added.splitlines():
            lines.append(f"+{L}")
    if body_removed:
        for L in body_removed.splitlines():
            lines.append(f"-{L}")
    return "\n".join(lines) + "\n"


class TestLowRiskApprovals(unittest.TestCase):
    def test_docs_patch_auto_merge(self):
        d = diff("docs/RUNBOOK.md", body_added="new section")
        r = pv.validate_patch(d)
        self.assertEqual(r.verdict, "APPROVE_AUTO_MERGE")
        self.assertEqual(r.risk_category, "LOW_RISK")

    def test_test_patch_auto_merge(self):
        d = diff("tests/architecture_vnext/test_new.py",
                  body_added="def test_x(): pass")
        r = pv.validate_patch(d)
        self.assertEqual(r.verdict, "APPROVE_AUTO_MERGE")

    def test_health_script_auto_merge(self):
        d = diff("scripts/trading_health.py", body_added="# extra check")
        r = pv.validate_patch(d)
        self.assertEqual(r.verdict, "APPROVE_AUTO_MERGE")


class TestMediumRisk(unittest.TestCase):
    def test_portfolio_risk_patch_pr_only(self):
        d = diff("shared/portfolio_risk.py", body_added="MAX_FOO = 1")
        r = pv.validate_patch(d)
        self.assertEqual(r.verdict, "APPROVE_PR_ONLY")
        self.assertEqual(r.risk_category, "MEDIUM_RISK")

    def test_signal_confirmation_patch_pr_only(self):
        d = diff("shared/signal_confirmation.py",
                  body_added="DEFAULT_VOLUME_RATIO_MIN = 1.30")
        r = pv.validate_patch(d)
        self.assertEqual(r.verdict, "APPROVE_PR_ONLY")


class TestHighRiskAndForbidden(unittest.TestCase):
    def test_alpaca_orders_high_risk(self):
        d = diff("shared/alpaca_orders.py", body_added="x = 1")
        r = pv.validate_patch(d)
        self.assertIn(r.verdict, ("REJECT_FORBIDDEN", "REJECT_HIGH_RISK"))
        self.assertNotEqual(r.verdict, "APPROVE_AUTO_MERGE")

    def test_risk_officer_high_risk(self):
        d = diff("shared/risk_officer.py", body_added="x = 1")
        r = pv.validate_patch(d)
        self.assertIn(r.verdict, ("REJECT_FORBIDDEN", "REJECT_HIGH_RISK"))

    def test_self_modify_validator_forbidden(self):
        d = diff("learning-loop/patch_validator.py",
                  body_added="LOW_RISK_PATHS = ('/',)")
        r = pv.validate_patch(d)
        self.assertEqual(r.verdict, "REJECT_FORBIDDEN")

    def test_live_endpoint_rejected(self):
        d = diff("scripts/some_script.py",
                  body_added="URL = 'https://api.alpaca.markets/v2/account'")
        r = pv.validate_patch(d)
        self.assertEqual(r.verdict, "REJECT_FORBIDDEN")

    def test_live_trading_flag_rejected(self):
        d = diff("shared/runtime_config.py",
                  body_added='LIVE_TRADING = "true"')
        r = pv.validate_patch(d)
        self.assertEqual(r.verdict, "REJECT_FORBIDDEN")

    def test_test_skip_marker_rejected(self):
        d = diff("tests/architecture_vnext/test_existing.py",
                  body_added="@unittest.skip('flaky')")
        r = pv.validate_patch(d)
        self.assertEqual(r.verdict, "REJECT_FORBIDDEN")

    def test_dependency_change_high_risk(self):
        d = diff("requirements.txt", body_added="boto3==1.0")
        r = pv.validate_patch(d)
        self.assertIn(r.verdict, ("REJECT_FORBIDDEN", "REJECT_HIGH_RISK"))

    def test_eval_exec_rejected(self):
        d = diff("scripts/trading_health.py",
                  body_added="eval(user_input)")
        r = pv.validate_patch(d)
        self.assertEqual(r.verdict, "REJECT_FORBIDDEN")

    def test_secret_literal_rejected(self):
        d = diff("scripts/audit_workflows.py",
                  body_added="TOKEN = 'sk-ant-abcdefghijklmnopqrstuvwxyz0123'")
        r = pv.validate_patch(d)
        self.assertEqual(r.verdict, "REJECT_FORBIDDEN")


class TestEmptyAndMalformed(unittest.TestCase):
    def test_empty_diff_rejected(self):
        r = pv.validate_patch("")
        self.assertEqual(r.verdict, "REJECT_FORBIDDEN")

    def test_unclassified_path_high_risk(self):
        d = diff("some/random/path.py", body_added="x = 1")
        r = pv.validate_patch(d)
        self.assertEqual(r.verdict, "REJECT_HIGH_RISK")


class TestRemovedTest(unittest.TestCase):
    def test_removed_test_definition_rejected(self):
        bad_diff = "\n".join([
            "diff --git a/tests/test_foo.py b/tests/test_foo.py",
            "--- a/tests/test_foo.py",
            "+++ b/tests/test_foo.py",
            "@@ -1,2 +1,1 @@",
            "-def test_existing():",
            "-    assert True",
            " ",
        ])
        r = pv.validate_patch(bad_diff)
        self.assertIn(r.verdict, ("REJECT_FORBIDDEN", "REJECT_HIGH_RISK"))


if __name__ == "__main__":
    unittest.main()
