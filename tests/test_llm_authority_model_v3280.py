"""v3.28 (2026-06-09) — LLM authority model tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestAuthorityLevels(unittest.TestCase):
    def test_all_levels_enumerated(self):
        import llm_advisory_registry as r
        for tok in (
            "L0_OBSERVE_ONLY", "L1_EXPLAIN_ONLY",
            "L2_RECOMMEND_ONLY", "L3_VETO_RECOMMEND_ONLY",
            "L4_PROPOSE_CONFIG_CHANGE_ONLY",
        ):
            self.assertIn(getattr(r, tok), r.ALL_AUTHORITY_LEVELS)
            self.assertIn(getattr(r, tok), r.ASSIGNABLE_LEVELS)

    def test_l5_is_not_assignable(self):
        import llm_advisory_registry as r
        self.assertEqual(r.L5_EXECUTE_FORBIDDEN,
                          "L5_EXECUTE_FORBIDDEN")
        self.assertNotIn(r.L5_EXECUTE_FORBIDDEN, r.ASSIGNABLE_LEVELS)
        self.assertNotIn(r.L5_EXECUTE_FORBIDDEN, r.ALL_AUTHORITY_LEVELS)

    def test_assert_assignable_authority_rejects_l5(self):
        import llm_advisory_registry as r
        with self.assertRaises(ValueError):
            r.assert_assignable_authority(r.L5_EXECUTE_FORBIDDEN)

    def test_assert_assignable_authority_rejects_unknown(self):
        import llm_advisory_registry as r
        with self.assertRaises(ValueError):
            r.assert_assignable_authority("L99_UNKNOWN")

    def test_authority_doc_exists(self):
        path = REPO_ROOT / "docs" / "LLM_AUTHORITY_MODEL.md"
        self.assertTrue(path.exists())


class TestRegistryEnforcesContract(unittest.TestCase):
    def test_every_agent_has_required_forbidden_actions(self):
        import llm_advisory_registry as r
        required = set(r.FORBIDDEN_ACTIONS)
        for agent in r.all_agents():
            self.assertTrue(
                required.issubset(set(agent.forbidden_actions)),
                f"{agent.name} forbidden_actions missing some "
                f"of {sorted(required)}")

    def test_every_agent_max_authority_l3_except_risk_proposal(self):
        import llm_advisory_registry as r
        max_l3 = {r.L0_OBSERVE_ONLY, r.L1_EXPLAIN_ONLY,
                   r.L2_RECOMMEND_ONLY, r.L3_VETO_RECOMMEND_ONLY}
        for agent in r.all_agents():
            if agent.name == "RISK_GATE_CHANGE_PROPOSAL_AGENT":
                self.assertEqual(
                    agent.authority_level,
                    r.L4_PROPOSE_CONFIG_CHANGE_ONLY)
            else:
                self.assertIn(
                    agent.authority_level, max_l3,
                    f"{agent.name} authority {agent.authority_level} "
                    f"exceeds L3 ceiling")

    def test_constructing_agent_with_l5_raises(self):
        import llm_advisory_registry as r
        with self.assertRaises(ValueError):
            r.AgentDefinition(
                name="BAD_AGENT",
                process_stage=r.MARKET_REGIME,
                authority_level=r.L5_EXECUTE_FORBIDDEN,
                allowed_inputs=("x",),
                forbidden_actions=r.FORBIDDEN_ACTIONS,
                output_schema="x",
                max_calls_per_run=1,
                fail_soft_behavior="x",
                prompt_template="x",
            )


if __name__ == "__main__":
    unittest.main()
