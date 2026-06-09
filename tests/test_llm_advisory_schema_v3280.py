"""v3.28 (2026-06-09) — advisory schema enum tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestSchemaPinsSafetyEnums(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = (REPO_ROOT / "learning-loop" / "llm_advisory"
                 / "schema.json")
        cls.schema = json.loads(path.read_text(encoding="utf-8"))
        cls.props = cls.schema["properties"]

    def test_advisory_only_enum_pinned_true(self):
        self.assertEqual(self.props["advisory_only"]["enum"], [True])

    def test_may_execute_enum_pinned_false(self):
        self.assertEqual(self.props["may_execute"]["enum"], [False])

    def test_may_modify_risk_enum_pinned_false(self):
        self.assertEqual(self.props["may_modify_risk"]["enum"], [False])

    def test_may_unlock_broker_paper_enum_pinned_false(self):
        self.assertEqual(
            self.props["may_unlock_broker_paper"]["enum"], [False])

    def test_broker_order_submitted_enum_pinned_false(self):
        self.assertEqual(
            self.props["broker_order_submitted"]["enum"], [False])

    def test_broker_execution_enabled_enum_pinned_false(self):
        self.assertEqual(
            self.props["broker_execution_enabled"]["enum"], [False])

    def test_affects_readiness_gate_enum_pinned_false(self):
        self.assertEqual(
            self.props["affects_readiness_gate"]["enum"], [False])

    def test_authority_level_excludes_l5_sentinel(self):
        levels = set(self.props["authority_level"]["enum"])
        self.assertNotIn("L5_EXECUTE_FORBIDDEN", levels)
        self.assertIn("L0_OBSERVE_ONLY", levels)
        self.assertIn("L3_VETO_RECOMMEND_ONLY", levels)
        self.assertIn("L4_PROPOSE_CONFIG_CHANGE_ONLY", levels)

    def test_process_stages_complete(self):
        stages = set(self.props["process_stage"]["enum"])
        for s in (
            "MARKET_REGIME", "SIGNAL_REVIEW",
            "NO_SIGNAL_DIAGNOSTIC", "SHADOW_OPPORTUNITY_REVIEW",
            "SHADOW_OUTCOME_REVIEW", "PRE_ORDER_ADVISORY",
            "RISK_NARRATIVE_REVIEW", "RISK_GATE_CHANGE_PROPOSAL",
            "INCIDENT_REVIEW", "BROKER_PAPER_CANARY_REVIEW",
            "FINAL_ADVISORY_ARBITER",
        ):
            self.assertIn(s, stages)

    def test_forbidden_actions_enum_complete(self):
        items = set(
            self.props["forbidden_actions_confirmed"]["items"]["enum"])
        for a in (
            "ORDER_EXECUTION", "POSITION_MODIFICATION",
            "RISK_GATE_DIRECT_MUTATION", "BROKER_PAPER_UNLOCK",
            "LIVE_TRADING_ENABLEMENT", "BASELINE_RESET",
            "DRAWDOWN_GUARD_LOWERING", "READINESS_COUNTER_MUTATION",
            "MARKET_DATA_FABRICATION", "PNL_FABRICATION",
        ):
            self.assertIn(a, items)


if __name__ == "__main__":
    unittest.main()
