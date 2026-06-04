"""v3.18.0 (2026-06-04) — Tests for shared/strategy_quality_gate.py.

Covers classification rules + edge_gate_decision invariants. Every test
runs with emit_audit=False so we don't pollute journal/autonomy/ during
unit runs (and so we don't depend on shared.audit being available).
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))


class _BaseQualityGateTest(unittest.TestCase):
    def setUp(self):
        # Force-fresh import; the module loads classify_strategy + thresholds.
        for k in list(sys.modules):
            if k.endswith(".strategy_quality_gate") \
               or k == "strategy_quality_gate":
                del sys.modules[k]
        import strategy_quality_gate as sqg
        self.sqg = sqg

    def _good_metrics(self, n: int = 60, wr: float = 0.55,
                      pf: float = 1.50, expectancy: float = 5.0,
                      max_dd: float = 0.10, net_pnl: float = 500.0,
                      last_20_wr: float = 0.55,
                      per_regime: dict | None = None) -> dict:
        return {
            "n_closed":     n,
            "win_rate":     wr,
            "profit_factor": pf,
            "expectancy":   expectancy,
            "avg_win":      10.0,
            "avg_loss":    -5.0,
            "max_drawdown": max_dd,
            "longest_losing_streak": 3,
            "net_pnl_after_fees_slippage": net_pnl,
            "gross_pnl":    net_pnl + 50.0,
            "total_costs":  50.0,
            "last_20_win_rate": last_20_wr,
            "per_regime":   per_regime if per_regime is not None else {
                "RISK_ON":  {"n_closed": 30, "expectancy": 5.0,
                              "net_pnl_after_fees_slippage": 250.0},
                "RISK_OFF": {"n_closed": 20, "expectancy": 3.0,
                              "net_pnl_after_fees_slippage": 100.0},
            },
        }


# ─── classify_strategy ────────────────────────────────────────────────────────

class TestClassifyStrategy(_BaseQualityGateTest):

    def test_audit_incomplete_returns_rejected(self):
        m = self._good_metrics()
        s = self.sqg.classify_strategy("momentum-long", m,
                                        audit_complete=False,
                                        emit_audit=False)
        self.assertEqual(s, self.sqg.REJECTED)

    def test_risk_violations_returns_rejected(self):
        m = self._good_metrics()
        s = self.sqg.classify_strategy("momentum-long", m,
                                        risk_violations_recent=2,
                                        emit_audit=False)
        self.assertEqual(s, self.sqg.REJECTED)

    def test_n_below_10_observe_only(self):
        m = self._good_metrics(n=5)
        s = self.sqg.classify_strategy("momentum-long", m,
                                        emit_audit=False)
        self.assertEqual(s, self.sqg.OBSERVE_ONLY)

    def test_n_between_10_and_50_paper_candidate(self):
        m = self._good_metrics(n=25, last_20_wr=0.55)
        s = self.sqg.classify_strategy("momentum-long", m,
                                        emit_audit=False)
        self.assertEqual(s, self.sqg.PAPER_CANDIDATE)

    def test_edge_approved_for_experiment_full_criteria(self):
        m = self._good_metrics(
            n=60, wr=0.55, pf=1.50, net_pnl=500.0, max_dd=0.15,
            last_20_wr=0.55,
            per_regime={
                "RISK_ON":  {"n_closed": 30, "expectancy": 5.0,
                              "net_pnl_after_fees_slippage": 250.0},
                "RISK_OFF": {"n_closed": 20, "expectancy": 3.0,
                              "net_pnl_after_fees_slippage": 100.0},
            },
        )
        s = self.sqg.classify_strategy("momentum-long", m,
                                        emit_audit=False)
        self.assertEqual(s, self.sqg.EDGE_APPROVED_FOR_EXPERIMENT)

    def test_pf_just_below_threshold_downgrades_to_candidate(self):
        m = self._good_metrics(n=60, wr=0.50, pf=1.15,
                                net_pnl=100.0, max_dd=0.15,
                                last_20_wr=0.50)
        s = self.sqg.classify_strategy("momentum-long", m,
                                        emit_audit=False)
        self.assertEqual(s, self.sqg.EDGE_CANDIDATE)

    def test_pf_above_1_below_candidate_threshold_paper_enabled(self):
        # n>=50 (past PAPER_CANDIDATE band) AND PF>=1.0 but PF<1.10
        # (below EDGE_CANDIDATE) → PAPER_ENABLED "keep collecting".
        m = self._good_metrics(n=55, wr=0.45, pf=1.05,
                                net_pnl=50.0, last_20_wr=0.40)
        s = self.sqg.classify_strategy("momentum-long", m,
                                        emit_audit=False)
        self.assertEqual(s, self.sqg.PAPER_ENABLED)

    def test_negative_expectancy_disables(self):
        m = self._good_metrics(n=60, wr=0.30, pf=0.5,
                                net_pnl=-300.0, last_20_wr=0.40)
        s = self.sqg.classify_strategy("momentum-long", m,
                                        emit_audit=False)
        self.assertEqual(s, self.sqg.DISABLED)

    def test_recent_degradation_disables(self):
        # n>=20 needed for degradation check. Last 20 WR < 30% → DISABLED.
        m = self._good_metrics(n=60, wr=0.55, pf=1.50,
                                net_pnl=500.0, last_20_wr=0.20)
        s = self.sqg.classify_strategy("momentum-long", m,
                                        emit_audit=False)
        self.assertEqual(s, self.sqg.DISABLED)

    def test_only_one_positive_regime_downgrades_from_edge(self):
        m = self._good_metrics(
            n=60, wr=0.55, pf=1.50, net_pnl=500.0, max_dd=0.10,
            last_20_wr=0.55,
            per_regime={
                "RISK_ON":  {"n_closed": 60, "expectancy": 5.0,
                              "net_pnl_after_fees_slippage": 500.0},
            },
        )
        s = self.sqg.classify_strategy("momentum-long", m,
                                        emit_audit=False)
        # Only 1 regime → drops out of EDGE_APPROVED_FOR_EXPERIMENT.
        self.assertNotEqual(s, self.sqg.EDGE_APPROVED_FOR_EXPERIMENT)
        # PF>=1.10 → EDGE_CANDIDATE
        self.assertEqual(s, self.sqg.EDGE_CANDIDATE)

    def test_max_dd_too_high_downgrades_from_edge(self):
        m = self._good_metrics(
            n=60, wr=0.55, pf=1.50, net_pnl=500.0,
            max_dd=0.40,  # > 25%
            last_20_wr=0.55,
        )
        s = self.sqg.classify_strategy("momentum-long", m,
                                        emit_audit=False)
        self.assertEqual(s, self.sqg.EDGE_CANDIDATE)

    def test_not_applicable_registry_returns_disabled(self):
        # crypto-breakdown is NOT_APPLICABLE per registry
        m = self._good_metrics(n=60)
        s = self.sqg.classify_strategy("crypto-breakdown", m,
                                        emit_audit=False)
        self.assertEqual(s, self.sqg.DISABLED)

    def test_alloc_exit_not_applicable(self):
        m = self._good_metrics(n=100)
        s = self.sqg.classify_strategy("alloc-exit", m, emit_audit=False)
        self.assertEqual(s, self.sqg.DISABLED)

    def test_classify_strategy_emits_audit_when_enabled(self):
        m = self._good_metrics()
        with mock.patch.object(self.sqg, "_emit_audit") as emit:
            self.sqg.classify_strategy("momentum-long", m,
                                       audit_complete=False,
                                       emit_audit=True)
            self.assertTrue(emit.called)
        # And NOT called when disabled.
        with mock.patch.object(self.sqg, "_emit_audit") as emit:
            self.sqg.classify_strategy("momentum-long", m,
                                       audit_complete=False,
                                       emit_audit=False)
            self.assertFalse(emit.called)

    def test_missing_strategy_name_rejected(self):
        s = self.sqg.classify_strategy("", {}, emit_audit=False)
        self.assertEqual(s, self.sqg.REJECTED)

    def test_metrics_not_a_dict_rejected(self):
        s = self.sqg.classify_strategy("anything", "not a dict",   # type: ignore
                                        emit_audit=False)
        self.assertEqual(s, self.sqg.REJECTED)


# ─── edge_gate_decision ─────────────────────────────────────────────────────

class TestEdgeGateDecision(_BaseQualityGateTest):

    def test_returns_false_when_fewer_than_2_approved(self):
        statuses = {
            "s1": self.sqg.EDGE_APPROVED_FOR_EXPERIMENT,
            "s2": self.sqg.PAPER_ENABLED,
        }
        # Mock audit cleared so we isolate the approved-count check.
        with mock.patch.object(self.sqg, "_audit_findings_cleared",
                                return_value=(True, [])):
            allow, blockers = self.sqg.edge_gate_decision(statuses)
        self.assertFalse(allow)
        self.assertTrue(any("EDGE_APPROVED" in b for b in blockers))

    def test_returns_false_when_any_rejected(self):
        statuses = {
            "s1": self.sqg.EDGE_APPROVED_FOR_EXPERIMENT,
            "s2": self.sqg.EDGE_APPROVED_FOR_EXPERIMENT,
            "s3": self.sqg.REJECTED,
        }
        with mock.patch.object(self.sqg, "_audit_findings_cleared",
                                return_value=(True, [])):
            allow, blockers = self.sqg.edge_gate_decision(statuses)
        self.assertFalse(allow)
        self.assertTrue(any("REJECTED" in b for b in blockers))

    def test_returns_true_only_when_all_criteria_met(self):
        statuses = {
            "s1": self.sqg.EDGE_APPROVED_FOR_EXPERIMENT,
            "s2": self.sqg.EDGE_APPROVED_FOR_EXPERIMENT,
            "s3": self.sqg.PAPER_ENABLED,
        }
        with mock.patch.object(self.sqg, "_audit_findings_cleared",
                                return_value=(True, [])):
            allow, blockers = self.sqg.edge_gate_decision(statuses)
        self.assertTrue(allow)
        self.assertEqual(blockers, [])

    def test_returns_false_when_audit_unresolved(self):
        statuses = {
            "s1": self.sqg.EDGE_APPROVED_FOR_EXPERIMENT,
            "s2": self.sqg.EDGE_APPROVED_FOR_EXPERIMENT,
        }
        with mock.patch.object(self.sqg, "_audit_findings_cleared",
                                return_value=(False, ["P0 finding unresolved"])):
            allow, blockers = self.sqg.edge_gate_decision(statuses)
        self.assertFalse(allow)
        self.assertTrue(any("P0" in b for b in blockers))

    def test_bad_input_returns_false(self):
        allow, blockers = self.sqg.edge_gate_decision("not a dict")  # type: ignore
        self.assertFalse(allow)
        self.assertTrue(blockers)

    def test_classify_all_aggregator(self):
        m_good = self._good_metrics(n=60)
        m_bad  = self._good_metrics(n=5)
        statuses = self.sqg.classify_all(
            {"momentum-long": m_good, "crypto-momentum": m_bad},
            audit_complete=True,
            emit_audit=False,
        )
        self.assertEqual(statuses["momentum-long"],
                          self.sqg.EDGE_APPROVED_FOR_EXPERIMENT)
        self.assertEqual(statuses["crypto-momentum"],
                          self.sqg.OBSERVE_ONLY)


# ─── LIVE_APPROVED absence guard ─────────────────────────────────────────────

class TestNoLiveApproval(_BaseQualityGateTest):
    def test_no_status_named_live_approved(self):
        for s in self.sqg.ALL_STATUSES:
            self.assertNotIn("LIVE", s.upper(),
                              f"status '{s}' looks live-trade-adjacent")

    def test_thresholds_are_finite_floats(self):
        self.assertIsInstance(self.sqg.MIN_WR_FOR_EDGE, float)
        self.assertIsInstance(self.sqg.MIN_PF_FOR_EDGE, float)
        self.assertGreater(self.sqg.MIN_PF_FOR_EDGE, 1.0)


if __name__ == "__main__":
    unittest.main()
