"""v3.20.0 (2026-06-04) — Tests for shared/gate_calibration.py.

Covers the contracts from ETAP 9:
  * Per-gate breakdown is correct.
  * Risk-gate rejected_good_signals are labelled safety_correct_rejection
    (NOT trading_opportunity_miss).
  * protection_value sums absolute avoided losses.
  * net_gate_value carries the right sign.
  * The risk gate CANNOT be auto-weakened — invariant raises.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _mk_cf(gate, outcome, *, decision="REJECTED",
           horizon=24, pnl_after_costs=0.0, missed=0.0):
    from counterfactual_outcomes import CounterfactualResult
    is_profitable = outcome == "PROFITABLE"
    is_losing = outcome == "LOSING"
    was_correct = None
    if decision in ("REJECTED", "OBSERVE_ONLY"):
        if is_profitable:
            was_correct = False
        elif is_losing or outcome == "FLAT":
            was_correct = True
    return CounterfactualResult(
        signal_id=f"cf-{gate}-{outcome}-{decision}",
        symbol="XYZ",
        side="long",
        horizon_hours=horizon,
        decision=decision,
        gate=gate,
        entry_ts="2026-06-03T00:00:00Z",
        entry_price=100.0,
        horizon_price=100.0 + pnl_after_costs,
        hypothetical_pnl_pct=pnl_after_costs,
        hypothetical_pnl_after_costs_pct=pnl_after_costs,
        mfe_pct=max(0.0, pnl_after_costs),
        mae_pct=min(0.0, pnl_after_costs),
        outcome=outcome,
        was_rejection_correct=was_correct,
        missed_opportunity_cost_pct=missed,
    )


class TestGateCalibration(unittest.TestCase):

    def setUp(self):
        for k in list(sys.modules):
            if k in ("gate_calibration", "counterfactual_outcomes"):
                del sys.modules[k]
        from gate_calibration import (
            GATE_CONFIDENCE, GATE_RISK, GATE_UNIVERSE,
            build_calibration_report, RiskGateInvariantViolation,
            assert_risk_gate_cannot_weaken,
        )
        self.GATE_CONFIDENCE = GATE_CONFIDENCE
        self.GATE_RISK = GATE_RISK
        self.GATE_UNIVERSE = GATE_UNIVERSE
        self.build = build_calibration_report
        self.invariant_exc = RiskGateInvariantViolation
        self.assert_invariant = assert_risk_gate_cannot_weaken

        self.tmp = tempfile.mkdtemp()
        os.environ["AUDIT_TRADING_DIR"] = self.tmp

    def tearDown(self):
        os.environ.pop("AUDIT_TRADING_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_per_gate_breakdowns(self):
        """Each gate accumulates its own rejection/acceptance counts."""
        cfs = [
            _mk_cf(self.GATE_CONFIDENCE, "LOSING", pnl_after_costs=-1.5),
            _mk_cf(self.GATE_CONFIDENCE, "LOSING", pnl_after_costs=-0.8),
            _mk_cf(self.GATE_CONFIDENCE, "PROFITABLE",
                   pnl_after_costs=2.0, missed=2.0),
            _mk_cf(self.GATE_UNIVERSE, "PROFITABLE",
                   pnl_after_costs=1.0, missed=1.0),
        ]
        report = self.build(cfs, executed_trades=[], horizon_hours=24,
                            emit_audit=False)
        conf = report.find(self.GATE_CONFIDENCE)
        uni = report.find(self.GATE_UNIVERSE)
        self.assertIsNotNone(conf)
        self.assertIsNotNone(uni)
        # 2 correct rejections, 1 false rejection.
        self.assertEqual(conf.rejected_bad_signals, 2)
        self.assertEqual(conf.rejected_good_signals, 1)
        # 1 false rejection on universe.
        self.assertEqual(uni.rejected_good_signals, 1)
        self.assertEqual(uni.rejected_bad_signals, 0)

    def test_risk_gate_rejection_labelled_safety(self):
        """rejected_good_signals on the risk gate → safety_correct_rejection."""
        cfs = [
            _mk_cf(self.GATE_RISK, "PROFITABLE", pnl_after_costs=3.0, missed=3.0),
            _mk_cf(self.GATE_RISK, "LOSING", pnl_after_costs=-2.0),
        ]
        report = self.build(cfs, executed_trades=[], horizon_hours=24,
                            emit_audit=False)
        risk = report.find(self.GATE_RISK)
        self.assertIsNotNone(risk)
        self.assertEqual(risk.safety_correct_rejection, 1)
        self.assertEqual(risk.trading_opportunity_miss, 0)
        # false_rejection_rate forced to 0 on risk gate.
        self.assertEqual(risk.false_rejection_rate, 0.0)
        # missed_opportunity_estimate also suppressed.
        self.assertEqual(risk.missed_opportunity_estimate, 0.0)

    def test_protection_value_sums_avoided_losses(self):
        """rejected_bad_signals contribute their absolute loss to protection."""
        cfs = [
            _mk_cf(self.GATE_CONFIDENCE, "LOSING", pnl_after_costs=-1.5),
            _mk_cf(self.GATE_CONFIDENCE, "LOSING", pnl_after_costs=-2.5),
            _mk_cf(self.GATE_CONFIDENCE, "FLAT", pnl_after_costs=0.0),
        ]
        report = self.build(cfs, executed_trades=[], horizon_hours=24,
                            emit_audit=False)
        conf = report.find(self.GATE_CONFIDENCE)
        self.assertAlmostEqual(conf.protection_value, 1.5 + 2.5 + 0.0,
                               places=4)

    def test_net_gate_value(self):
        """net_gate_value == protection - missed (per gate; never < 0 trivially)."""
        cfs = [
            _mk_cf(self.GATE_CONFIDENCE, "LOSING", pnl_after_costs=-3.0),
            _mk_cf(self.GATE_CONFIDENCE, "PROFITABLE",
                   pnl_after_costs=1.0, missed=1.0),
        ]
        report = self.build(cfs, executed_trades=[], horizon_hours=24,
                            emit_audit=False)
        conf = report.find(self.GATE_CONFIDENCE)
        self.assertAlmostEqual(conf.net_gate_value, 3.0 - 1.0, places=4)

        # For the risk gate: missed always 0 → net == protection.
        risk_cfs = [
            _mk_cf(self.GATE_RISK, "LOSING", pnl_after_costs=-1.0),
            _mk_cf(self.GATE_RISK, "PROFITABLE", pnl_after_costs=5.0, missed=5.0),
        ]
        report_r = self.build(risk_cfs, executed_trades=[], horizon_hours=24,
                              emit_audit=False)
        risk = report_r.find(self.GATE_RISK)
        self.assertEqual(risk.missed_opportunity_estimate, 0.0)
        self.assertEqual(risk.net_gate_value, risk.protection_value)

    def test_risk_gate_cannot_auto_weaken_invariant(self):
        """assert_risk_gate_cannot_weaken raises for any tuning intent."""
        with self.assertRaises(self.invariant_exc):
            self.assert_invariant("risk", proposed_action="lower_threshold")
        with self.assertRaises(self.invariant_exc):
            self.assert_invariant("RISK", proposed_action="auto_disable")
        # And confidence is allowed to be tuned freely.
        try:
            self.assert_invariant("confidence",
                                  proposed_action="lower_threshold")
        except self.invariant_exc:
            self.fail("confidence gate must be tunable")

    def test_accepted_trades_split_good_vs_bad(self):
        """Executed paper trades contribute to accepted_good/bad per gate."""
        executed = [
            {"gates_passed": ["confidence"], "pnl_after_costs_pct": 2.5},
            {"gates_passed": ["confidence", "risk"],
             "pnl_after_costs_pct": -1.8},
        ]
        report = self.build([], executed_trades=executed, horizon_hours=24,
                            emit_audit=False)
        conf = report.find("confidence")
        risk = report.find("risk")
        self.assertEqual(conf.accepted_good_trades, 1)
        self.assertEqual(conf.accepted_bad_trades, 1)
        # The losing trade also passed through risk → counts there.
        self.assertEqual(risk.accepted_bad_trades, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
