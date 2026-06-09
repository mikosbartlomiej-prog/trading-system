"""v3.28 (2026-06-09) — global "LLM has zero execution authority" tests.

Scans every v3.28 module + script + the workflow YAML and asserts that
none of them import or call any of the broker-orders / order-submission
APIs. This is the single most important safety test of the sprint.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Every v3.28 file that participates in the advisory mesh.
V3280_FILES = (
    "shared/llm_agent_budget.py",
    "shared/llm_provider_client.py",
    "shared/llm_advisory_registry.py",
    "shared/llm_pre_order_advisory.py",
    "shared/llm_risk_change_proposal.py",
    "scripts/run_llm_advisory_mesh.py",
    ".github/workflows/llm-advisory-mesh.yml",
)

FORBIDDEN_TOKENS = (
    "alpaca_orders",
    "safe_close",
    "place_stock_bracket",
    "place_crypto_order",
    "place_simple_buy",
    "place_options_buy",
    "place_oco_exit",
    "execute_stock_signal",
    "execute_crypto_signal",
    "submit_order",
    "place_order",
)


class TestNoBrokerExecution(unittest.TestCase):
    def test_no_forbidden_tokens_in_any_v3280_file(self):
        for rel in V3280_FILES:
            path = REPO_ROOT / rel
            self.assertTrue(path.exists(), f"missing: {rel}")
            text = path.read_text(encoding="utf-8")
            for tok in FORBIDDEN_TOKENS:
                self.assertNotIn(
                    tok, text,
                    f"forbidden token {tok!r} found in {rel}")


class TestNoBrokerHost(unittest.TestCase):
    def test_no_paper_api_alpaca_in_any_v3280_file(self):
        for rel in V3280_FILES:
            path = REPO_ROOT / rel
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("paper-api.alpaca.markets", text,
                              f"broker host in {rel}")


class TestNoReadinessGateMutation(unittest.TestCase):
    def test_no_evidence_counters_write(self):
        for rel in V3280_FILES:
            path = REPO_ROOT / rel
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(
                "evidence_counters_latest.json\", \"w", text,
                f"counter mutation in {rel}")

    def test_no_edge_gate_or_allow_broker_paper_writes(self):
        for rel in V3280_FILES:
            path = REPO_ROOT / rel
            text = path.read_text(encoding="utf-8")
            for tok in ('EDGE_GATE_ENABLED = "true"',
                         'ALLOW_BROKER_PAPER = "true"',
                         'BROKER_EXECUTION_ENABLED = "true"',
                         'LIVE_TRADING = "true"'):
                self.assertNotIn(tok, text,
                                  f"unsafe assignment in {rel}: {tok}")


class TestAdvisoryAuthorityPinnedToL3OrL4(unittest.TestCase):
    def test_registry_caps_agents(self):
        sys.path.insert(0, str(REPO_ROOT / "shared"))
        import llm_advisory_registry as r
        forbidden_levels = {"L5_EXECUTE_FORBIDDEN", "L6_GOD_MODE"}
        for agent in r.all_agents():
            self.assertNotIn(agent.authority_level, forbidden_levels)
            # L4 is reserved for the single risk-proposal agent.
            if agent.authority_level == r.L4_PROPOSE_CONFIG_CHANGE_ONLY:
                self.assertEqual(agent.name,
                                  "RISK_GATE_CHANGE_PROPOSAL_AGENT")


class TestAdvisorySchemaContractIsBroadcast(unittest.TestCase):
    def test_pre_order_result_to_dict_contract(self):
        sys.path.insert(0, str(REPO_ROOT / "shared"))
        import llm_pre_order_advisory as a
        d = a.AdvisoryResult(
            verdict=a.ADVISORY_PASS, reason="x").to_dict()
        self.assertTrue(d["advisory_only"])
        self.assertFalse(d["may_execute"])
        self.assertFalse(d["may_modify_risk"])
        self.assertFalse(d["may_unlock_broker_paper"])
        self.assertFalse(d["broker_order_submitted"])
        self.assertFalse(d["broker_execution_enabled"])
        self.assertFalse(d["affects_readiness_gate"])

    def test_risk_proposal_to_dict_contract(self):
        sys.path.insert(0, str(REPO_ROOT / "shared"))
        import llm_risk_change_proposal as r
        p = r.build_proposal(
            current_config_ref="x", proposed_change={},
            rationale="x", expected_effect="x")
        d = p.to_dict()
        self.assertFalse(d["auto_apply"])
        self.assertTrue(d["requires_operator_approval"])
        self.assertTrue(d["advisory_only"])


if __name__ == "__main__":
    unittest.main()
