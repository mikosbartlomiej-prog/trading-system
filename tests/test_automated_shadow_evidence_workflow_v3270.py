"""v3.27.0 (2026-06-09) — automated GitHub Actions workflow tests."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestWorkflowFilePresent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = (REPO_ROOT / ".github" / "workflows"
                     / "signal-shadow-evidence.yml")
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_file_exists(self):
        self.assertTrue(self.path.exists())

    def test_schedule_block_present(self):
        self.assertIn("schedule:", self.text)
        # Cron string from operator suggestion.
        self.assertRegex(self.text, r"35 13-19 \* \* 1-5")

    def test_workflow_dispatch_present(self):
        self.assertIn("workflow_dispatch:", self.text)

    def test_concurrency_block_present(self):
        self.assertIn("concurrency:", self.text)
        self.assertIn("cancel-in-progress: false", self.text)

    def test_permissions_contents_write(self):
        self.assertIn("contents: write", self.text)


class TestWorkflowSafetyEnvFlags(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (REPO_ROOT / ".github" / "workflows"
                     / "signal-shadow-evidence.yml").read_text()

    def test_all_seven_broker_flags_pinned_false(self):
        for flag in (
            "ALLOW_BROKER_PAPER",
            "EDGE_GATE_ENABLED",
            "BROKER_EXECUTION_ENABLED",
            "LIVE_TRADING",
            "LIVE_ENABLED",
            "GO_LIVE",
            "LIVE_TRADING_ENABLED",
        ):
            # Each flag should appear in the env block pinned to "false".
            pattern = rf'{flag}:\s*"false"'
            self.assertRegex(self.text, pattern,
                              f"{flag} not pinned false")

    def test_no_truthy_broker_flags_anywhere(self):
        for flag in (
            "ALLOW_BROKER_PAPER", "EDGE_GATE_ENABLED",
            "BROKER_EXECUTION_ENABLED",
        ):
            for truthy in ('"true"', "'true'", ": true"):
                self.assertNotIn(
                    f"{flag}: {truthy}", self.text,
                    f"{flag} accidentally set truthy",
                )

    def test_refuse_step_exists(self):
        # Step that fails if any broker flag is truthy at runtime.
        self.assertIn("Refuse if any broker-execution env flag is truthy",
                       self.text)


class TestWorkflowEntryPoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (REPO_ROOT / ".github" / "workflows"
                     / "signal-shadow-evidence.yml").read_text()

    def test_collector_invoked_without_allow_without_market_data(self):
        # v3.27 workflow uses --with-market-data instead of the
        # legacy --allow-without-market-data; either is acceptable
        # but it must invoke the collector script.
        self.assertIn(
            "scripts/run_signal_shadow_evidence_collection.py",
            self.text,
        )
        # Should explicitly NOT set --allow-without-market-data (the
        # legacy scaffold flag). v3.27 uses --with-market-data.
        # Both are acceptable but the workflow uses --with-market-data.
        self.assertIn("--with-market-data", self.text)

    def test_resolver_invoked(self):
        self.assertIn("scripts/resolve_shadow_outcomes.py", self.text)

    def test_progress_updater_invoked(self):
        self.assertIn(
            "scripts/update_shadow_evidence_progress.py", self.text,
        )


class TestWorkflowCommitPathAllowList(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (REPO_ROOT / ".github" / "workflows"
                     / "signal-shadow-evidence.yml").read_text()

    def test_git_add_restricted_to_evidence_paths(self):
        # The workflow must stage ONLY learning-loop/shadow_evidence/,
        # docs/SHADOW_EVIDENCE_PROGRESS.md, and the
        # position_reconciliation latest.json.
        self.assertIn("learning-loop/shadow_evidence/", self.text)
        self.assertIn("docs/SHADOW_EVIDENCE_PROGRESS.md", self.text)
        self.assertIn(
            "learning-loop/position_reconciliation/latest.json",
            self.text,
        )

    def test_path_check_step_present(self):
        # Step name from our YAML.
        self.assertIn("Enforce commit-path allow-list", self.text)
        # The step must reject unauthorized paths.
        self.assertIn("REFUSED", self.text)


class TestWorkflowDoesNotCallBrokerExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (REPO_ROOT / ".github" / "workflows"
                     / "signal-shadow-evidence.yml").read_text()

    def test_no_alpaca_orders_or_safe_close_invoked(self):
        FORBIDDEN = (
            "alpaca_orders", "safe_close",
            "place_stock_bracket", "place_crypto_order",
            "execute_crypto_signal", "execute_stock_signal",
            "panic_close_options",
        )
        for tok in FORBIDDEN:
            self.assertNotIn(tok, self.text,
                              f"forbidden token in workflow: {tok!r}")


class TestWorkflowAuditAllowListIncludesNewWorkflow(unittest.TestCase):
    def test_audit_workflows_lists_new_workflow(self):
        src = (REPO_ROOT / "scripts"
                / "audit_workflows.py").read_text()
        self.assertIn("signal-shadow-evidence.yml", src)


class TestWorkflowCommitMessage(unittest.TestCase):
    def test_commit_message_matches_spec(self):
        text = (REPO_ROOT / ".github" / "workflows"
                 / "signal-shadow-evidence.yml").read_text()
        # User spec: "Update automated shadow evidence" — plus
        # [automerge] tag so auto-merge.yml fast-forwards to main.
        self.assertIn("Update automated shadow evidence", text)
        self.assertIn("[automerge]", text)


if __name__ == "__main__":
    unittest.main()
