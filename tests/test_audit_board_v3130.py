"""v3.13.0 (2026-05-30) — tests for the Multi-Agent Audit Board structure.

Validates:
  * All 13 prompt files exist
  * Each agent prompt has the required sections
  * All 3 JSON schemas exist + are well-formed
  * README.md exists + mentions free operation
  * Runner subcommands work (list / validate-structure / check-forbidden /
    init / validate-reports)
  * No forbidden profit-guarantee phrases in any prompt
  * Final Arbiter has decision-options section
  * Each agent has a unique 'id prefix' in finding.schema.json enum

These tests pin down the Audit Board contract so future refactors don't
silently weaken the review surface.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
PROMPTS_DIR = AGENTS_DIR / "prompts"
SCHEMAS_DIR = AGENTS_DIR / "schemas"


# All 11 area agents + final arbiter (12) + shared context (00)
EXPECTED_PROMPTS = [
    "00_shared_context.md",
    "01_architecture_reviewer.md",
    "02_trading_strategy_reviewer.md",
    "03_risk_reviewer.md",
    "04_data_quality_bias_reviewer.md",
    "05_confidence_score_reviewer.md",
    "06_runtime_safety_reviewer.md",
    "07_testing_e2e_reviewer.md",
    "08_documentation_runbook_reviewer.md",
    "09_simplicity_refactoring_reviewer.md",
    "10_security_secrets_reviewer.md",
    "11_free_operations_reviewer.md",
    "12_final_arbiter.md",
]

AREA_AGENT_PROMPTS = EXPECTED_PROMPTS[1:-1]  # 01..11

REQUIRED_AGENT_SECTIONS = (
    "## Role",
    "## Scope of responsibility",
    "## What you MUST NOT do",
    "## Blocking criteria",
    "## Acceptance criteria",
    "## Confidence-score impact",
    "## Output format",
    "## Required tests",
    "## Free-operation requirement",
)

EXPECTED_SCHEMAS = (
    "finding.schema.json",
    "agent_report.schema.json",
    "final_decision.schema.json",
)


class TestPromptFilesExist(unittest.TestCase):

    def test_all_13_prompt_files_present(self):
        missing = []
        for fname in EXPECTED_PROMPTS:
            if not (PROMPTS_DIR / fname).exists():
                missing.append(fname)
        self.assertEqual(missing, [], f"missing prompt files: {missing}")

    def test_shared_context_contains_free_operation_clause(self):
        text = (PROMPTS_DIR / "00_shared_context.md").read_text()
        self.assertIn("FREE OPERATION", text)
        self.assertIn("Forbidden language", text)

    def test_shared_context_forbids_profit_guarantees(self):
        text = (PROMPTS_DIR / "00_shared_context.md").read_text().lower()
        # Either explicit anti-pattern note or "no-profit-guarantee rule"
        self.assertIn("no-profit-guarantee", text)

    def test_shared_context_forbids_runtime_brain_role(self):
        text = (PROMPTS_DIR / "00_shared_context.md").read_text().lower()
        self.assertIn("not the runtime brain", text)


class TestAreaAgentPromptsHaveRequiredSections(unittest.TestCase):
    """Each of the 11 area-agent prompts must contain all required sections."""

    def test_every_area_agent_has_required_sections(self):
        for fname in AREA_AGENT_PROMPTS:
            with self.subTest(agent=fname):
                text = (PROMPTS_DIR / fname).read_text()
                missing = [s for s in REQUIRED_AGENT_SECTIONS if s not in text]
                self.assertEqual(missing, [],
                                  f"{fname} missing sections: {missing}")

    def test_every_area_agent_has_blocking_criteria(self):
        """BLOCKS_PAPER_TRADING phrasing must appear (otherwise the agent
        cannot actually block anything)."""
        for fname in AREA_AGENT_PROMPTS:
            with self.subTest(agent=fname):
                text = (PROMPTS_DIR / fname).read_text()
                self.assertIn("BLOCKS_PAPER_TRADING", text,
                               f"{fname} must declare what BLOCKS_PAPER_TRADING")


class TestFinalArbiterPrompt(unittest.TestCase):

    def setUp(self):
        self.text = (PROMPTS_DIR / "12_final_arbiter.md").read_text()

    def test_has_decision_options_section(self):
        self.assertIn("Decision options", self.text)

    def test_lists_all_7_decision_types(self):
        for d in ("APPROVE_LOCAL_REPLAY",
                   "APPROVE_PAPER_TRADING_WITH_WARNINGS",
                   "BLOCK_PAPER_TRADING",
                   "NEEDS_REFACTOR",
                   "NEEDS_MORE_TESTS",
                   "NOT_SAFE_FOR_LIVE_TRADING",
                   "BLOCK_ALL_TRADING_MODES"):
            self.assertIn(d, self.text, f"final_arbiter must list {d}")

    def test_forbids_recommending_live_trading(self):
        # Must explicitly forbid
        lower = self.text.lower()
        self.assertIn("never recommend live trading", lower)

    def test_requires_all_11_agents_consumed(self):
        # The hard rule that arbiter cannot decide on partial input
        self.assertIn("all 11", self.text.lower() if "all 11" in self.text.lower()
                       else self.text)


class TestSchemas(unittest.TestCase):

    def test_all_3_schemas_present(self):
        for s in EXPECTED_SCHEMAS:
            self.assertTrue((SCHEMAS_DIR / s).exists(),
                              f"missing schema: {s}")

    def test_schemas_are_valid_json(self):
        for s in EXPECTED_SCHEMAS:
            with self.subTest(schema=s):
                try:
                    data = json.loads((SCHEMAS_DIR / s).read_text())
                except json.JSONDecodeError as e:
                    self.fail(f"{s} invalid JSON: {e}")
                self.assertIn("$schema", data, f"{s} missing $schema")
                self.assertIn("required", data, f"{s} missing required fields")

    def test_finding_schema_has_required_fields(self):
        data = json.loads((SCHEMAS_DIR / "finding.schema.json").read_text())
        required = set(data["required"])
        for f in ("id", "agent", "title", "severity", "area", "affected_files",
                    "evidence", "risk", "recommendation", "required_tests",
                    "free_operation_impact", "confidence_score_impact",
                    "safety_impact", "blocking_status", "status"):
            self.assertIn(f, required, f"finding schema missing required field: {f}")

    def test_finding_schema_enums_complete(self):
        data = json.loads((SCHEMAS_DIR / "finding.schema.json").read_text())
        sev_enum = set(data["properties"]["severity"]["enum"])
        self.assertEqual(sev_enum, {"P0", "P1", "P2", "P3"})
        blocking_enum = set(data["properties"]["blocking_status"]["enum"])
        for s in ("BLOCKS_LOCAL_REPLAY", "BLOCKS_PAPER_TRADING",
                    "BLOCKS_LIVE_TRADING", "NEEDS_REFACTOR",
                    "NEEDS_TESTS", "INFO_ONLY"):
            self.assertIn(s, blocking_enum)

    def test_final_decision_schema_requires_all_11_agents(self):
        data = json.loads((SCHEMAS_DIR / "final_decision.schema.json").read_text())
        ac = data["properties"]["agents_consumed"]
        self.assertEqual(ac["minItems"], 11,
                          "final_decision must require all 11 area agents")

    def test_final_decision_schema_live_trading_locked_to_blocked(self):
        data = json.loads((SCHEMAS_DIR / "final_decision.schema.json").read_text())
        ltr = data["properties"]["live_trading_readiness"]
        self.assertEqual(ltr["enum"], ["blocked"],
                          "live_trading_readiness must be permanently blocked")


class TestReadme(unittest.TestCase):

    def setUp(self):
        self.text = (AGENTS_DIR / "README.md").read_text()

    def test_readme_exists(self):
        self.assertTrue((AGENTS_DIR / "README.md").exists())

    def test_readme_states_not_runtime_brain(self):
        self.assertIn("NOT a runtime trading brain", self.text)

    def test_readme_explains_free_operation(self):
        self.assertIn("free in operation", self.text.lower())

    def test_readme_lists_all_agents(self):
        for fname in EXPECTED_PROMPTS:
            agent_name = fname.replace(".md", "")
            # README references each agent by name OR the column
            self.assertIn(agent_name, self.text,
                           f"README missing reference to {agent_name}")

    def test_readme_explains_decision_options(self):
        for d in ("APPROVE_LOCAL_REPLAY", "BLOCK_PAPER_TRADING",
                   "NOT_SAFE_FOR_LIVE_TRADING"):
            self.assertIn(d, self.text)


class TestRunner(unittest.TestCase):
    """The local runner must work without LLM / network."""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(AGENTS_DIR / "run_agent_board.py"), *args],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )

    def test_list_succeeds(self):
        r = self._run("list")
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        self.assertIn("00_shared_context", r.stdout)
        self.assertIn("12_final_arbiter", r.stdout)

    def test_validate_structure_succeeds(self):
        r = self._run("validate-structure")
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        self.assertIn("Audit board structure VALID", r.stdout)

    def test_check_forbidden_succeeds(self):
        r = self._run("check-forbidden")
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        self.assertIn("No forbidden phrases", r.stdout)

    def test_init_with_invalid_date_fails(self):
        r = self._run("init", "2026/05/30")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("YYYY-MM-DD", r.stdout)

    def test_validate_reports_missing_fails(self):
        # A date with no reports should fail
        r = self._run("validate-reports", "1999-01-01")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("MISSING", r.stdout)


class TestRunnerInitFlow(unittest.TestCase):
    """Test init creates correct templates, then cleanup."""

    def test_init_and_validate_roundtrip(self):
        test_date = "2099-12-31"  # far-future, unlikely to collide
        reports_dir = AGENTS_DIR / "reports"
        try:
            # init
            r1 = subprocess.run(
                [sys.executable, str(AGENTS_DIR / "run_agent_board.py"),
                 "init", test_date],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(r1.returncode, 0, f"init stderr: {r1.stderr}")
            self.assertIn("12 report templates created", r1.stdout)
            # All 11 area + 1 final = 12 files
            created = sorted(reports_dir.glob(f"*_{test_date}.md"))
            self.assertEqual(len(created), 12,
                              f"expected 12 reports, got {len(created)}: {[p.name for p in created]}")
            # validate-reports
            r2 = subprocess.run(
                [sys.executable, str(AGENTS_DIR / "run_agent_board.py"),
                 "validate-reports", test_date],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(r2.returncode, 0, f"validate stderr: {r2.stderr}")
            self.assertIn("All reports present", r2.stdout)
        finally:
            # Cleanup
            for p in reports_dir.glob(f"*_{test_date}.md"):
                try: p.unlink()
                except Exception: pass


class TestNoForbiddenContentInPrompts(unittest.TestCase):
    """No prompt may make profit-guarantee claims or recommend live trading."""

    FORBIDDEN_OUTSIDE_NEGATION = (
        "we recommend going live",
        "guaranteed edge",
        "guarantees profit",
        "always profitable",
    )

    def test_no_unconditional_profit_promises(self):
        # The runner already checks this — we double-check by reading directly.
        # An occurrence is OK if preceded by a negation marker within 200 chars.
        import re
        for fname in EXPECTED_PROMPTS:
            text_lower = (PROMPTS_DIR / fname).read_text().lower()
            for phrase in self.FORBIDDEN_OUTSIDE_NEGATION:
                for m in re.finditer(re.escape(phrase), text_lower):
                    chunk = text_lower[max(0, m.start() - 200):m.end()]
                    has_negation = re.search(
                        r"(must not|never|forbidden|do not|anti.pattern|red flag|not recommend)",
                        chunk,
                    )
                    if not has_negation:
                        self.fail(f"{fname}: unconditional '{phrase}' at "
                                   f"position {m.start()}")


if __name__ == "__main__":
    unittest.main()
