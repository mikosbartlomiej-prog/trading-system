"""v3.28 (2026-06-09) — advisory registry tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestAllElevenAgentsPresent(unittest.TestCase):
    def test_eleven_agents_in_registry(self):
        import llm_advisory_registry as r
        names = {a.name for a in r.all_agents()}
        for name in (
            "MARKET_REGIME_AGENT",
            "SIGNAL_QUALITY_AGENT",
            "DATA_QUALITY_AGENT",
            "NO_SIGNAL_DIAGNOSTIC_AGENT",
            "SHADOW_OUTCOME_REVIEW_AGENT",
            "PRE_ORDER_ADVISORY_AGENT",
            "RISK_NARRATIVE_AGENT",
            "RISK_GATE_CHANGE_PROPOSAL_AGENT",
            "INCIDENT_REVIEW_AGENT",
            "BROKER_PAPER_CANARY_REVIEW_AGENT",
            "FINAL_ADVISORY_ARBITER",
        ):
            self.assertIn(name, names)


class TestAgentForbiddenActions(unittest.TestCase):
    def test_every_agent_lists_all_ten_forbidden(self):
        import llm_advisory_registry as r
        for agent in r.all_agents():
            for a in r.FORBIDDEN_ACTIONS:
                self.assertIn(
                    a, agent.forbidden_actions,
                    f"{agent.name} missing forbidden action {a!r}")


class TestPreOrderAuthorityIsL3(unittest.TestCase):
    def test_pre_order_max_authority(self):
        import llm_advisory_registry as r
        agent = r.agent_for("PRE_ORDER_ADVISORY_AGENT")
        self.assertEqual(agent.authority_level,
                          r.L3_VETO_RECOMMEND_ONLY)


class TestRiskProposalIsL4(unittest.TestCase):
    def test_risk_proposal_l4(self):
        import llm_advisory_registry as r
        agent = r.agent_for("RISK_GATE_CHANGE_PROPOSAL_AGENT")
        self.assertEqual(agent.authority_level,
                          r.L4_PROPOSE_CONFIG_CHANGE_ONLY)


class TestUnknownAgentRaises(unittest.TestCase):
    def test_unknown_agent_keyerror(self):
        import llm_advisory_registry as r
        with self.assertRaises(KeyError):
            r.agent_for("UNKNOWN_AGENT_XYZ")


class TestNoBrokerImports(unittest.TestCase):
    def test_source_clean(self):
        src = (REPO_ROOT / "shared"
                / "llm_advisory_registry.py").read_text(encoding="utf-8")
        for tok in ("alpaca_orders", "safe_close",
                     "place_stock_bracket", "place_crypto_order"):
            self.assertNotIn(tok, src)


if __name__ == "__main__":
    unittest.main()
