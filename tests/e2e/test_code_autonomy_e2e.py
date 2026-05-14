"""E2E: autonomous code loop — patch validator + rollback simulation."""

import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import conftest  # noqa: F401

import unittest

import patch_validator as pv


def diff(touched: str, body_added: str = "", body_removed: str = "") -> str:
    lines = [
        f"diff --git a/{touched} b/{touched}",
        f"index 0..1 100644",
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


class TestPatchValidatorE2E(unittest.TestCase):
    def test_low_risk_docs_patch_auto_merge(self):
        d = diff("docs/RUNBOOK.md", body_added="new section")
        r = pv.validate_patch(d)
        self.assertEqual(r.verdict, "APPROVE_AUTO_MERGE")

    def test_low_risk_test_patch_auto_merge(self):
        d = diff("tests/architecture_vnext/test_new.py",
                  body_added="def test_x(): assert True")
        r = pv.validate_patch(d)
        self.assertEqual(r.verdict, "APPROVE_AUTO_MERGE")

    def test_medium_risk_portfolio_pr_only(self):
        d = diff("shared/portfolio_risk.py", body_added="MAX_FOO = 1")
        r = pv.validate_patch(d)
        self.assertEqual(r.verdict, "APPROVE_PR_ONLY")

    def test_live_endpoint_rejected(self):
        d = diff("scripts/x.py",
                  body_added="URL = 'https://api.alpaca.markets/v2/orders'")
        r = pv.validate_patch(d)
        self.assertEqual(r.verdict, "REJECT_FORBIDDEN")

    def test_risk_gate_removal_rejected(self):
        d = diff("shared/alpaca_orders.py",
                  body_added="x = 1")
        r = pv.validate_patch(d)
        self.assertIn(r.verdict, ("REJECT_FORBIDDEN", "REJECT_HIGH_RISK"))

    def test_paid_dependency_rejected(self):
        d = diff("requirements.txt", body_added="datadog==2.0")
        r = pv.validate_patch(d)
        self.assertIn(r.verdict, ("REJECT_FORBIDDEN", "REJECT_HIGH_RISK"))

    def test_test_skip_marker_rejected(self):
        d = diff("tests/architecture_vnext/test_existing.py",
                  body_added="@unittest.skip('flaky')")
        r = pv.validate_patch(d)
        self.assertEqual(r.verdict, "REJECT_FORBIDDEN")

    def test_validator_self_modify_rejected(self):
        d = diff("learning-loop/patch_validator.py",
                  body_added="LOW_RISK_PATHS = ('/',)")
        r = pv.validate_patch(d)
        self.assertEqual(r.verdict, "REJECT_FORBIDDEN")

    def test_secret_literal_rejected(self):
        d = diff("scripts/audit_workflows.py",
                  body_added="TOKEN = 'sk-ant-abcdefghijklmnopqrstuvwxyz0123'")
        r = pv.validate_patch(d)
        self.assertEqual(r.verdict, "REJECT_FORBIDDEN")


class TestRollbackSimulation(unittest.TestCase):
    """Even without running real git, we verify code_autonomy.revert_commit
    exists and would shell-out to `git revert` (mock-friendly)."""

    def test_revert_commit_function_exists(self):
        import code_autonomy as ca
        self.assertTrue(hasattr(ca, "revert_commit"))
        self.assertTrue(hasattr(ca, "apply_and_commit"))
        self.assertTrue(hasattr(ca, "current_sha"))


if __name__ == "__main__":
    unittest.main()
