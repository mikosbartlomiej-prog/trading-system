"""v3.21 (2026-06-04) — Multi-Agent Audit Board v3.21 prompt-coverage tests.

Verifies that 00_shared_context.md has v3.21 escalation triggers and
module references.

Tests NEVER call the LLM; they grep prompt files for required strings.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO_ROOT / "agents" / "prompts"


class TestSharedContextV321Coverage(unittest.TestCase):

    def setUp(self):
        self.text = (PROMPTS_DIR / "00_shared_context.md").read_text(encoding="utf-8")

    def test_v321_section_present(self):
        self.assertIn("v3.21 coverage", self.text)

    def test_evidence_throughput_statuses_documented(self):
        for status in (
            "NO_EVIDENCE_FLOW",
            "TOO_SLOW_TO_REACH_N50",
            "HEALTHY_SHADOW_FLOW",
            "HEALTHY_BROKER_PAPER_FLOW",
            "NEEDS_MORE_SYMBOLS",
            "NEEDS_MORE_SIGNAL_DENSITY",
            "NEEDS_MORE_REGIME_COVERAGE",
        ):
            self.assertIn(status, self.text, f"missing status: {status}")

    def test_signal_density_statuses_documented(self):
        for status in (
            "DEAD_STRATEGY",
            "TOO_SPARSE",
            "NOISY_STRATEGY",
            "HEALTHY_DENSITY",
            "HIGH_REJECTION_BUT_PROMISING",
            "NEEDS_VARIANT_DISCOVERY",
            "NEEDS_UNIVERSE_EXPANSION",
        ):
            self.assertIn(status, self.text, f"missing status: {status}")

    def test_runner_live_mode_rejected_rule(self):
        # Runner has no live mode and arbiter blocks --mode live invocation
        self.assertIn("LIVE_MODE_NOT_SUPPORTED", self.text)
        self.assertIn("--mode live", self.text)

    def test_multi_horizon_segregation_rule(self):
        self.assertIn("MULTI_HORIZON", self.text)
        self.assertIn("NEVER count as", self.text)

    def test_observation_priority_statuses(self):
        for status in (
            "PRIORITY_OBSERVE", "NORMAL_OBSERVE", "LOW_PRIORITY",
            "DO_NOT_OBSERVE", "NEEDS_DATA",
        ):
            self.assertIn(status, self.text, f"missing status: {status}")

    def test_discovery_sandbox_invariants(self):
        self.assertIn("DISCOVERY_NEVER_ENABLES_RUNTIME", self.text)
        self.assertIn("DISCOVERY_NEVER_PLACES_TRADES", self.text)
        self.assertIn("DISCOVERY_NEVER_REMOVES_GATES", self.text)

    def test_broker_paper_adapter_invariants(self):
        self.assertIn("ADAPTER_PAPER_ONLY", self.text)
        self.assertIn("ADAPTER_REQUIRES_IDEMPOTENCY", self.text)
        self.assertIn("ADAPTER_FAIL_CLOSED", self.text)
        self.assertIn("MAX_ORDER_NOTIONAL_USD=100", self.text)
        self.assertIn("SHADOW_FALLBACK", self.text)

    def test_fill_model_calibration_insufficient_data_rule(self):
        self.assertIn("INSUFFICIENT_BROKER_PAPER_DATA", self.text)
        self.assertIn("Does NOT mutate model", self.text)

    def test_evidence_budget_safety_bypass(self):
        self.assertIn("BUDGET_BYPASSES_SAFETY = True", self.text)

    def test_operator_action_queue_no_auto_apply(self):
        self.assertIn("QUEUE_NEVER_AUTO_APPLIES", self.text)
        self.assertIn("can_auto_apply=False", self.text)

    def test_v321_arbiter_section_present(self):
        self.assertIn("Final Arbiter v3.21 escalation triggers", self.text)

    def test_arbiter_blocks_on_runner_live_mode(self):
        self.assertIn("--mode live", self.text)

    def test_arbiter_blocks_on_broker_paper_no_assert(self):
        self.assertIn("broker_paper_adapter.py", self.text)
        self.assertIn("hard-assert paper URL", self.text)

    def test_arbiter_blocks_on_variant_runtime_writes(self):
        self.assertIn("writes a variant directly", self.text)

    def test_arbiter_blocks_on_zero_flow_five_days(self):
        self.assertIn("zero flow for 5+", self.text)

    def test_arbiter_blocks_on_auto_apply_queue(self):
        self.assertIn("can_auto_apply=True", self.text)

    def test_arbiter_blocks_on_budget_safety_violation(self):
        self.assertIn("BUDGET_BYPASSES_SAFETY=False", self.text)

    def test_arbiter_edge_gate_requires_paper_evidence(self):
        # SHADOW + COUNTERFACTUAL + MULTI_HORIZON do NOT satisfy
        self.assertIn("SHADOW + COUNTERFACTUAL + MULTI_HORIZON", self.text)
        self.assertIn('evidence_source="PAPER"', self.text)

    def test_arbiter_never_recommends_live_trading(self):
        # Already in v3.20 but verify still present
        self.assertIn("NEVER recommends LIVE_TRADING", self.text)


if __name__ == "__main__":
    unittest.main()
