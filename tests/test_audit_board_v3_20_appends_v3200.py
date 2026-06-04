"""v3.20 (2026-06-04) — Multi-Agent Audit Board v3.20 prompt-coverage tests.

Verifies that 00_shared_context.md (loaded by every reviewer) and the
Final Arbiter prompt have been extended with v3.20 escalation triggers
and module references.

Tests NEVER call the LLM; they grep prompt files for required strings.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO_ROOT / "agents" / "prompts"


class TestSharedContextV320Coverage(unittest.TestCase):

    def setUp(self):
        self.text = (PROMPTS_DIR / "00_shared_context.md").read_text(encoding="utf-8")

    def test_v320_section_present(self):
        self.assertIn("v3.20 coverage", self.text)

    def test_evidence_production_modes_documented(self):
        for mode in ("SIGNAL_ONLY", "SHADOW_PAPER_SIM", "BROKER_PAPER"):
            self.assertIn(mode, self.text, f"missing mode: {mode}")

    def test_opportunity_ledger_six_gate_types(self):
        for gate in ("confidence", "risk", "universe", "regime", "spread_slippage", "quality"):
            self.assertIn(gate, self.text, f"missing gate type: {gate}")

    def test_counterfactual_segregation_rule(self):
        # Counterfactual evidence cannot mix with paper
        self.assertIn("COUNTERFACTUAL", self.text)
        self.assertIn("MUST NOT count toward paper trade", self.text)

    def test_risk_gate_safety_correct_label(self):
        self.assertIn("safety_correct_rejection", self.text)
        self.assertIn("Risk gate NEVER auto-weakens", self.text)

    def test_evidence_lower_bounds_statuses(self):
        for status in (
            "EVIDENCE_TOO_WEAK",
            "EVIDENCE_IMPROVING",
            "EVIDENCE_ROBUST_CANDIDATE",
            "EVIDENCE_DEGRADING",
            "EVIDENCE_REJECT",
        ):
            self.assertIn(status, self.text, f"missing status: {status}")

    def test_variant_quarantine_statuses_no_live(self):
        for status in (
            "QUARANTINED",
            "REPLAY_TESTING",
            "SHADOW_OBSERVE",
            "REJECTED",
            "CANDIDATE_FOR_MANUAL_REVIEW",
        ):
            self.assertIn(status, self.text, f"missing variant status: {status}")
        self.assertIn("NO LIVE status", self.text)

    def test_edge_gate_criteria_documented(self):
        # EDGE_GATE flip criteria must be explicit
        self.assertIn("n>=50", self.text.replace(" ", ""))
        self.assertIn("PF_LB>=1.3", self.text.replace(" ", ""))


class TestFinalArbiterV320EscalationTriggers(unittest.TestCase):

    def setUp(self):
        # v3.20 escalation triggers live in shared context (every reviewer loads it)
        self.text = (PROMPTS_DIR / "00_shared_context.md").read_text(encoding="utf-8")

    def test_final_arbiter_escalation_section_present(self):
        self.assertIn("Final Arbiter v3.20 escalation triggers", self.text)

    def test_arbiter_blocks_on_mixed_evidence(self):
        self.assertIn(
            "counterfactual entries mixed into paper trade ledger",
            self.text,
        )

    def test_arbiter_blocks_on_variant_status_mutation(self):
        self.assertIn("variant status mutated", self.text)

    def test_arbiter_blocks_on_overfit_suspicion(self):
        self.assertIn("overfit_suspicion=true", self.text)

    def test_arbiter_blocks_on_edge_gate_without_criteria(self):
        self.assertIn("EDGE_GATE_ENABLED=true", self.text)

    def test_arbiter_never_recommends_live_trading(self):
        self.assertIn("NEVER recommends LIVE_TRADING", self.text)


class TestOperatorDecisionPackReferenced(unittest.TestCase):
    def test_decision_pack_path_documented(self):
        text = (PROMPTS_DIR / "00_shared_context.md").read_text(encoding="utf-8")
        self.assertIn("operator_decision_pack.py", text)
        self.assertIn("operator_decision_pack_LATEST", text)


if __name__ == "__main__":
    unittest.main()
