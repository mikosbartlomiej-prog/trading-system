"""v3.19.0 (2026-06-04) — Tests for ETAP 11 audit-board prompt appends.

Verifies that the 5 prompts (02, 04, 05, 07, 12) carry the new v3.19
evidence-source checklist / paper escalation block, and that the
multi-agent audit board runner still passes validate-structure +
check-forbidden after the appends.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS = REPO_ROOT / "agents" / "prompts"


APPENDED_PROMPTS = (
    "02_trading_strategy_reviewer.md",
    "04_data_quality_bias_reviewer.md",
    "05_confidence_score_reviewer.md",
    "07_testing_e2e_reviewer.md",
)
APPEND_MARKER = "v3.19 evidence-source checklist (appended 2026-06-04)"

ARBITER = "12_final_arbiter.md"
ARBITER_APPEND_MARKER = "v3.19 paper escalation block (appended 2026-06-04)"


def _read(name: str) -> str:
    p = PROMPTS / name
    assert p.exists(), f"missing prompt: {p}"
    return p.read_text(encoding="utf-8")


class TestAppendMarkers(unittest.TestCase):
    def test_each_of_5_prompts_has_marker(self):
        for name in APPENDED_PROMPTS:
            text = _read(name)
            self.assertIn(
                APPEND_MARKER, text,
                f"prompt {name} missing append marker",
            )
        arbiter_text = _read(ARBITER)
        self.assertIn(
            ARBITER_APPEND_MARKER, arbiter_text,
            f"final arbiter missing append marker",
        )


class TestTradingStrategyPrompt(unittest.TestCase):
    def test_02_has_paper_trades_ledger_check(self):
        text = _read("02_trading_strategy_reviewer.md")
        self.assertIn("Paper trades ledger", text)
        # n ≥ 50 threshold mentioned
        self.assertTrue(
            "n ≥ 50" in text or "n >= 50" in text,
            "prompt 02 must mention the n>=50 threshold for paper evidence",
        )


class TestConfidenceScorePrompt(unittest.TestCase):
    def test_05_has_calibration_check(self):
        text = _read("05_confidence_score_reviewer.md")
        self.assertIn("confidence_calibration_LATEST.md", text)
        self.assertIn("strategy_quality_gate", text)


class TestDataQualityPromptHasUniverseRanking(unittest.TestCase):
    def test_04_has_universe_ranking_check(self):
        text = _read("04_data_quality_bias_reviewer.md")
        self.assertIn("universe_ranking_LATEST.md", text)
        self.assertIn("Backtest/replay evidence is TRIAGE ONLY", text)


class TestTestingPromptCoversNewReports(unittest.TestCase):
    def test_07_has_evidence_sources(self):
        text = _read("07_testing_e2e_reviewer.md")
        self.assertIn("operator_dashboard_LATEST.md", text)
        self.assertIn("allocation_simulation_LATEST.md", text)


class TestFinalArbiter(unittest.TestCase):
    def test_12_has_block_paper_escalation_section(self):
        text = _read(ARBITER)
        self.assertIn("BLOCK paper escalation if", text)
        # Specific blockers required by the v3.19 spec
        self.assertIn("Paper ledger empty", text)
        self.assertIn("Confidence calibration uncalibrated", text)
        self.assertIn("EDGE_GATE_ENABLED=true without empirical criteria", text)
        self.assertIn(
            "Backtest/replay evidence used as paper approval", text)


class TestRunAgentBoardValidateStructure(unittest.TestCase):
    """The audit board runner must STILL pass validate-structure after the
    v3.19 appends.
    """

    def test_validate_structure_still_passes(self):
        runner = REPO_ROOT / "agents" / "run_agent_board.py"
        proc = subprocess.run(
            [sys.executable, str(runner), "validate-structure"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(
            proc.returncode, 0,
            f"validate-structure exited {proc.returncode}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )

    def test_check_forbidden_still_clean(self):
        runner = REPO_ROOT / "agents" / "run_agent_board.py"
        proc = subprocess.run(
            [sys.executable, str(runner), "check-forbidden"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(
            proc.returncode, 0,
            f"check-forbidden exited {proc.returncode}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )


class TestNoExistingContentLost(unittest.TestCase):
    """The appends must NOT have removed any of the existing required
    sections. We sample a few stable anchors per prompt."""

    EXPECTED_ANCHORS = {
        "02_trading_strategy_reviewer.md": (
            "## Role", "## Scope of responsibility",
            "## What you MUST NOT do",
            "## Blocking criteria", "## Acceptance criteria",
            "## Confidence-score impact", "## Output format",
            "## Required tests", "## Free-operation requirement",
        ),
        "04_data_quality_bias_reviewer.md": (
            "## Role", "## Output format", "## Free-operation requirement",
        ),
        "05_confidence_score_reviewer.md": (
            "## Role", "## Output format", "## Free-operation requirement",
        ),
        "07_testing_e2e_reviewer.md": (
            "## Role", "## Free-operation requirement",
        ),
        "12_final_arbiter.md": (
            "## Role", "## Decision options",
            "## What you MUST NOT do", "## Free-operation requirement",
        ),
    }

    def test_all_required_sections_still_present(self):
        for name, anchors in self.EXPECTED_ANCHORS.items():
            text = _read(name)
            for a in anchors:
                self.assertIn(
                    a, text,
                    f"prompt {name} lost required anchor section {a!r}",
                )


if __name__ == "__main__":
    unittest.main()
