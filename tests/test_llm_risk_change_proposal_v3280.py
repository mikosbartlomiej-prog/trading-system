"""v3.28 (2026-06-09) — risk-gate change proposal tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestProposalContract(unittest.TestCase):
    def test_proposal_auto_apply_false(self):
        import llm_risk_change_proposal as r
        p = r.build_proposal(
            current_config_ref="config/aggressive_profile.json",
            proposed_change={"foo": 1},
            rationale="test",
            expected_effect="test",
        )
        self.assertFalse(p.auto_apply)
        self.assertTrue(p.requires_operator_approval)
        self.assertTrue(p.advisory_only)

    def test_to_dict_pins_safety(self):
        import llm_risk_change_proposal as r
        p = r.build_proposal(
            current_config_ref="x", proposed_change={"a": 1},
            rationale="r", expected_effect="e")
        d = p.to_dict()
        self.assertFalse(d["auto_apply"])
        self.assertTrue(d["requires_operator_approval"])
        self.assertTrue(d["advisory_only"])
        self.assertTrue(d["requires_tests"])
        # Safety constraints contain all required forbidden actions.
        for a in (
            "ORDER_EXECUTION", "POSITION_MODIFICATION",
            "RISK_GATE_DIRECT_MUTATION", "BROKER_PAPER_UNLOCK",
            "LIVE_TRADING_ENABLEMENT", "BASELINE_RESET",
            "DRAWDOWN_GUARD_LOWERING", "READINESS_COUNTER_MUTATION",
        ):
            self.assertIn(a, d["safety_constraints"])

    def test_applies_to_risk_config_returns_false(self):
        import llm_risk_change_proposal as r
        p = r.build_proposal(
            current_config_ref="x", proposed_change={}, rationale="x",
            expected_effect="x")
        self.assertFalse(r.applies_to_risk_config(p))

    def test_cannot_force_auto_apply_true(self):
        import llm_risk_change_proposal as r
        with self.assertRaises(ValueError):
            r.RiskChangeProposal(
                proposal_id="x", agent_name="x",
                current_config_ref="x", proposed_change={},
                rationale="x", expected_effect="x",
                auto_apply=True,  # NOT allowed
            )

    def test_cannot_force_operator_approval_false(self):
        import llm_risk_change_proposal as r
        with self.assertRaises(ValueError):
            r.RiskChangeProposal(
                proposal_id="x", agent_name="x",
                current_config_ref="x", proposed_change={},
                rationale="x", expected_effect="x",
                requires_operator_approval=False,  # NOT allowed
            )


class TestProposalDoesNotModifyConfig(unittest.TestCase):
    def test_module_does_not_write_to_config(self):
        # Module has no file-write helpers.
        src = (REPO_ROOT / "shared"
                / "llm_risk_change_proposal.py").read_text(
            encoding="utf-8")
        for tok in ("open(", ".write(", ".write_text(",
                     "Path(", "subprocess", "os.system",
                     "shutil.copy", "shutil.move"):
            self.assertNotIn(tok, src,
                              f"risk proposal module must not touch "
                              f"disk: {tok}")


class TestNoBrokerImports(unittest.TestCase):
    def test_source_clean(self):
        src = (REPO_ROOT / "shared"
                / "llm_risk_change_proposal.py").read_text(encoding="utf-8")
        for tok in ("alpaca_orders", "safe_close",
                     "place_stock_bracket", "place_crypto_order",
                     "execute_stock_signal", "execute_crypto_signal"):
            self.assertNotIn(tok, src, f"forbidden: {tok}")


if __name__ == "__main__":
    unittest.main()
