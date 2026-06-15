"""v3.27.0 — Tests for ``.github/workflows/daily-reporters.yml`` v3.27 updates.

Verifies:
- All 4 v3.27 seeder steps are present in daily-reporters.yml.
- All 7 broker/live env flags are still pinned ``"false"``.
- No broker secrets (ALPACA_*) are referenced from the workflow.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "daily-reporters.yml"
)


class TestSeederStepsPresent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_daily_reporters_includes_seed_backfill(self):
        self.assertIn(
            "scripts/seed_backfill_snapshots.py",
            self.text,
            msg="daily-reporters.yml MUST invoke seed_backfill_snapshots.py",
        )

    def test_daily_reporters_includes_seed_near_miss(self):
        self.assertIn(
            "scripts/seed_near_miss_from_evidence.py",
            self.text,
            msg=("daily-reporters.yml MUST invoke "
                 "seed_near_miss_from_evidence.py"),
        )

    def test_daily_reporters_includes_seed_variant_quarantine(self):
        self.assertIn(
            "scripts/seed_strategy_variant_quarantine.py",
            self.text,
            msg=("daily-reporters.yml MUST invoke "
                 "seed_strategy_variant_quarantine.py"),
        )

    def test_daily_reporters_includes_seed_shadow_candidate_queue(self):
        self.assertIn(
            "scripts/seed_shadow_candidate_queue.py",
            self.text,
            msg=("daily-reporters.yml MUST invoke "
                 "seed_shadow_candidate_queue.py"),
        )

    def test_daily_reporters_includes_density_plan(self):
        self.assertIn(
            "scripts/build_opportunity_density_plan.py",
            self.text,
            msg=("daily-reporters.yml MUST invoke "
                 "build_opportunity_density_plan.py"),
        )


class TestSafetyPins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_daily_reporters_all_7_flags_pinned_false(self):
        """All 10 listed env flags MUST be pinned to "false".

        The task lists 7 broker/live flags; the workflow includes 3
        additional safety flags so the gate is even tighter.
        """
        required_flags = (
            "ALLOW_BROKER_PAPER",
            "EDGE_GATE_ENABLED",
            "BROKER_EXECUTION_ENABLED",
            "LIVE_TRADING",
            "LIVE_ENABLED",
            "GO_LIVE",
            "LIVE_TRADING_ENABLED",
            "LLM_PRE_ORDER_VETO_HONORED",
            "OPERATOR_APPROVED_BROKER_PAPER_CANARY",
            "LLM_AGENTS_SCHEDULED",
        )
        for flag in required_flags:
            # Pin pattern present in the workflow.
            self.assertIn(
                f'{flag}:', self.text,
                msg=f"{flag} not declared in workflow env block",
            )
            # Pinned value MUST be "false".
            # Search for either alignment style.
            patterns = (
                f'{flag}:                       "false"',
                f'{flag}:                                "false"',
                f'{flag}:                                       "false"',
                f'{flag}:                                          "false"',
                f'{flag}:    "false"',
                f'{flag}: "false"',
            )
            found = any(p in self.text for p in patterns)
            if not found:
                # Generic check: same line contains "false"
                line = next(
                    (l for l in self.text.splitlines()
                     if l.strip().startswith(f"{flag}:")),
                    "",
                )
                self.assertIn(
                    '"false"', line,
                    msg=f"{flag} MUST be pinned to \"false\"",
                )

    def test_daily_reporters_refuse_step_present(self):
        """Refuse step that exits non-zero on any truthy flag."""
        self.assertIn(
            "Refuse if any broker / live flag is truthy",
            self.text,
        )
        self.assertIn("REFUSED:", self.text)
        # The refuse block exits 1 explicitly.
        self.assertIn("exit 1", self.text)


class TestNoBrokerSecrets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_daily_reporters_no_broker_secrets(self):
        """Workflow MUST NOT reference broker API secrets."""
        # No secret references at all except GITHUB_TOKEN.
        forbidden_secrets = (
            "ALPACA_API_KEY",
            "ALPACA_SECRET_KEY",
            "ALPACA_SECRET",
            "APCA_API_KEY_ID",
            "APCA_API_SECRET_KEY",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "FINNHUB_API_KEY",
            "GMAIL_APP_PASSWORD",
        )
        for sec in forbidden_secrets:
            self.assertNotIn(
                sec, self.text,
                msg=f"daily-reporters.yml MUST NOT reference {sec}",
            )

    def test_daily_reporters_only_github_token_used(self):
        """Only the standard GITHUB_TOKEN may appear."""
        # Make sure the only ${{ secrets.* }} reference is GITHUB_TOKEN.
        lines = [
            l for l in self.text.splitlines()
            if "${{ secrets." in l
        ]
        for line in lines:
            self.assertIn(
                "GITHUB_TOKEN", line,
                msg=("only secrets.GITHUB_TOKEN may appear in "
                     f"daily-reporters.yml; saw: {line.strip()}"),
            )


if __name__ == "__main__":
    unittest.main()
