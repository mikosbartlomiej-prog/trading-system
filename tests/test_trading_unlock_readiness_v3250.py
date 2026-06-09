"""v3.25.0 (2026-06-09) — trading unlock readiness tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

import trading_unlock_readiness as ur


def _clean_inputs(**overrides) -> ur.UnlockReadinessInputs:
    """Defaults that yield SIGNAL_SHADOW_UNLOCK_READY but NOT
    broker-paper. Override fields to construct other scenarios."""
    i = ur.UnlockReadinessInputs()
    for k, v in overrides.items():
        setattr(i, k, v)
    return i


class TestCurrentStateNotBrokerPaperReady(unittest.TestCase):
    def test_default_clean_state_yields_signal_shadow(self):
        report = ur.evaluate_unlock_readiness(_clean_inputs())
        self.assertEqual(report.verdict, ur.SIGNAL_SHADOW_UNLOCK_READY)
        # Broker-paper has unmet conditions.
        self.assertGreater(len(report.missing_for_broker_paper), 0)

    def test_default_state_is_not_broker_paper_ready(self):
        report = ur.evaluate_unlock_readiness(_clean_inputs())
        self.assertNotEqual(report.verdict,
                             ur.BROKER_PAPER_CANARY_READY)


class TestSignalShadowBlockedWhenInvariantsHeld(unittest.TestCase):
    """Signal/shadow must be blocked if any hard invariant is violated."""

    def test_audit_bypass_unsatisfied_blocks(self):
        r = ur.evaluate_unlock_readiness(_clean_inputs(
            audit_bypass_invariant_satisfied=False,
        ))
        self.assertEqual(r.verdict, ur.TRADING_UNLOCK_BLOCKED)

    def test_active_legacy_script_blocks(self):
        r = ur.evaluate_unlock_readiness(_clean_inputs(
            no_active_legacy_dangerous_order_script=False,
        ))
        self.assertEqual(r.verdict, ur.TRADING_UNLOCK_BLOCKED)

    def test_open_equity_positions_blocks(self):
        r = ur.evaluate_unlock_readiness(_clean_inputs(
            open_equity_positions_count=3,
        ))
        self.assertEqual(r.verdict, ur.TRADING_UNLOCK_BLOCKED)

    def test_open_orders_blocks(self):
        r = ur.evaluate_unlock_readiness(_clean_inputs(
            open_orders_count=2,
        ))
        self.assertEqual(r.verdict, ur.TRADING_UNLOCK_BLOCKED)

    def test_crypto_hard_caps_missing_blocks(self):
        r = ur.evaluate_unlock_readiness(_clean_inputs(
            crypto_hard_exposure_caps_implemented=False,
        ))
        self.assertEqual(r.verdict, ur.TRADING_UNLOCK_BLOCKED)

    def test_baseline_silently_reset_blocks(self):
        r = ur.evaluate_unlock_readiness(_clean_inputs(
            baseline_silently_reset=True,
        ))
        self.assertEqual(r.verdict, ur.TRADING_UNLOCK_BLOCKED)

    def test_drawdown_guard_inactive_blocks(self):
        r = ur.evaluate_unlock_readiness(_clean_inputs(
            drawdown_guard_active_or_acknowledged=False,
        ))
        self.assertEqual(r.verdict, ur.TRADING_UNLOCK_BLOCKED)

    def test_edge_gate_flipped_blocks(self):
        r = ur.evaluate_unlock_readiness(_clean_inputs(
            edge_gate_enabled=True,
        ))
        self.assertEqual(r.verdict, ur.TRADING_UNLOCK_BLOCKED)

    def test_allow_broker_paper_flipped_blocks(self):
        r = ur.evaluate_unlock_readiness(_clean_inputs(
            allow_broker_paper=True,
        ))
        self.assertEqual(r.verdict, ur.TRADING_UNLOCK_BLOCKED)

    def test_tests_not_passing_blocks(self):
        r = ur.evaluate_unlock_readiness(_clean_inputs(
            v3_25_tests_pass=False,
        ))
        self.assertEqual(r.verdict, ur.TRADING_UNLOCK_BLOCKED)

    def test_unresolved_runaway_loop_blocks(self):
        r = ur.evaluate_unlock_readiness(_clean_inputs(
            unresolved_runaway_loop_finding=True,
        ))
        self.assertEqual(r.verdict, ur.TRADING_UNLOCK_BLOCKED)


class TestBrokerPaperRequiresEvidence(unittest.TestCase):
    def test_50_opportunities_required(self):
        i = _clean_inputs(
            normal_non_halt_opportunities_count=49,
            completed_shadow_outcomes_count=20,
            daily_learning_stable=True,
            trade_reconstruction_stable=True,
            explicit_operator_approval_for_broker_paper=True,
        )
        r = ur.evaluate_unlock_readiness(i)
        # Signal/shadow ready; broker paper not ready.
        self.assertEqual(r.verdict, ur.SIGNAL_SHADOW_UNLOCK_READY)
        # The missing list should reference the 50 threshold.
        missing_text = " ".join(r.missing_for_broker_paper)
        self.assertIn("50", missing_text)

    def test_20_shadow_outcomes_required(self):
        i = _clean_inputs(
            normal_non_halt_opportunities_count=50,
            completed_shadow_outcomes_count=19,
            daily_learning_stable=True,
            trade_reconstruction_stable=True,
            explicit_operator_approval_for_broker_paper=True,
        )
        r = ur.evaluate_unlock_readiness(i)
        self.assertEqual(r.verdict, ur.SIGNAL_SHADOW_UNLOCK_READY)
        missing_text = " ".join(r.missing_for_broker_paper)
        self.assertIn("20", missing_text)

    def test_broker_paper_ready_only_when_all_conditions_met(self):
        # v3.27.0: the gate consumes real_market_opportunities_count
        # (not the legacy normal_non_halt_opportunities_count).
        i = _clean_inputs(
            real_market_opportunities_count=100,
            normal_non_halt_opportunities_count=100,
            completed_shadow_outcomes_count=25,
            audit_bypass_findings_count=0,
            unexplained_exposure_growth_count=0,
            repeated_buy_loop_violations_count=0,
            crypto_exposure_cap_breached_count=0,
            daily_learning_stable=True,
            trade_reconstruction_stable=True,
            explicit_operator_approval_for_broker_paper=True,
        )
        r = ur.evaluate_unlock_readiness(i)
        self.assertEqual(r.verdict, ur.BROKER_PAPER_CANARY_READY)
        # Even at this elevated readiness, live trading remains
        # not-supported.
        self.assertEqual(r.details["higher_tier_status"],
                          ur.LIVE_TRADING_NOT_SUPPORTED)

    def test_operator_approval_required_even_with_evidence(self):
        i = _clean_inputs(
            normal_non_halt_opportunities_count=100,
            completed_shadow_outcomes_count=25,
            daily_learning_stable=True,
            trade_reconstruction_stable=True,
            explicit_operator_approval_for_broker_paper=False,
        )
        r = ur.evaluate_unlock_readiness(i)
        # Operator approval missing → still signal/shadow.
        self.assertEqual(r.verdict, ur.SIGNAL_SHADOW_UNLOCK_READY)


class TestLiveTradingAlwaysBlocked(unittest.TestCase):
    """No combination of inputs may return LIVE_TRADING_NOT_SUPPORTED
    as a positive verdict — it is a marker for the highest possible
    informational tier."""

    def test_live_not_in_verdict_set_for_positive_outcomes(self):
        # Even with every flag set positively, the verdict must NOT be
        # LIVE_TRADING_NOT_SUPPORTED.
        i = _clean_inputs(
            normal_non_halt_opportunities_count=100,
            completed_shadow_outcomes_count=25,
            daily_learning_stable=True,
            trade_reconstruction_stable=True,
            explicit_operator_approval_for_broker_paper=True,
        )
        r = ur.evaluate_unlock_readiness(i)
        self.assertIn(r.verdict, (
            ur.BROKER_PAPER_CANARY_READY,
            ur.SIGNAL_SHADOW_UNLOCK_READY,
        ))
        self.assertNotEqual(r.verdict, ur.LIVE_TRADING_NOT_SUPPORTED)


class TestEnvFlagsNotFlipped(unittest.TestCase):
    """The module must not require — and must visibly fail if — the
    operator has flipped any kill switch."""

    def test_edge_gate_env_false(self):
        self.assertNotEqual(
            os.environ.get("EDGE_GATE_ENABLED", "false").lower(),
            "true",
        )

    def test_allow_broker_paper_env_unset(self):
        self.assertNotEqual(
            os.environ.get("ALLOW_BROKER_PAPER", "false").lower(),
            "true",
        )

    def test_evaluate_from_current_repo_state_returns_signal_shadow(self):
        # With env flags off, the convenience helper should return
        # signal/shadow under the cleanish defaults provided.
        r = ur.evaluate_from_current_repo_state()
        self.assertEqual(r.verdict, ur.SIGNAL_SHADOW_UNLOCK_READY)


class TestNoOrderPlacingFunctions(unittest.TestCase):
    def test_no_forbidden_imports_or_calls(self):
        src = (REPO_ROOT / "shared"
                / "trading_unlock_readiness.py").read_text()
        FORBIDDEN = (
            "place_crypto_order", "place_stock_bracket",
            "place_simple_buy", "safe_close",
            "execute_crypto_signal", "execute_stock_signal",
            "requests.post", "requests.put", "requests.delete",
            'EDGE_GATE_ENABLED = "true"',
            'ALLOW_BROKER_PAPER = "true"',
        )
        for token in FORBIDDEN:
            self.assertNotIn(token, src,
                              f"forbidden token in unlock module: {token}")


class TestInvariants(unittest.TestCase):
    def test_invariants_true(self):
        self.assertTrue(ur.BROKER_PAPER_REQUIRES_EVIDENCE)
        self.assertTrue(ur.LIVE_TRADING_NEVER_RETURNS_READY)
        self.assertTrue(ur.NEVER_LOWERS_DRAWDOWN_GUARD)
        self.assertTrue(ur.NEVER_RESETS_BASELINE)
        self.assertTrue(ur.NEVER_FLIPS_EDGE_GATE)

    def test_all_verdicts_set(self):
        for v in (
            ur.TRADING_UNLOCK_BLOCKED,
            ur.SIGNAL_SHADOW_UNLOCK_READY,
            ur.BROKER_PAPER_CANARY_NOT_READY,
            ur.BROKER_PAPER_CANARY_READY,
            ur.LIVE_TRADING_NOT_SUPPORTED,
        ):
            self.assertIn(v, ur.ALL_VERDICTS)


if __name__ == "__main__":
    unittest.main()
