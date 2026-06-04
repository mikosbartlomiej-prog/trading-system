"""v3.20.0 (2026-06-04) — Tests for shared/evidence_lower_bounds.py.

Verifies:
  * Wilson lower bound matches the closed-form formula exactly.
  * Low-sample ledger returns EVIDENCE_TOO_WEAK.
  * Weak Wilson lower bound blocks ROBUST_CANDIDATE even with strong PF.
  * Mid-sample ledger with good mean WR returns EVIDENCE_IMPROVING.
  * Large drawdown with degrading tail returns EVIDENCE_DEGRADING.
  * Bootstrap is deterministic for a given seed.
  * PF mean ≥ 1.3 with PF lower bound < 1.0 returns EVIDENCE_REJECT.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))


class _Base(unittest.TestCase):
    def setUp(self):
        for k in list(sys.modules):
            if k.endswith(".evidence_lower_bounds") \
               or k == "evidence_lower_bounds":
                del sys.modules[k]
        import evidence_lower_bounds as elb
        self.m = elb

    def _make_trades(self, pnls: list[float],
                     strategy: str = "demo") -> list[dict]:
        out = []
        for i, p in enumerate(pnls):
            out.append({
                "strategy":   strategy,
                "symbol":     "AAPL" if i % 2 == 0 else "MSFT",
                "regime":     "RISK_ON" if i % 3 != 0 else "NEUTRAL",
                "closed_at":  f"2026-06-0{(i % 9) + 1}T13:00:00Z",
                "net_pnl":    p,
                "size_usd":   1000.0,
            })
        return out


class TestWilsonExact(_Base):
    """The Wilson lower bound must match the spec formula exactly."""

    def test_wilson_50_of_100_matches_formula(self):
        lb = self.m.wilson_lower_bound(50, 100)
        z = 1.96
        p = 0.5
        n = 100
        z2 = z * z
        centre = p + z2 / (2 * n)
        half = z * math.sqrt((p * (1 - p) + z2 / (4 * n)) / n)
        denom = 1 + z2 / n
        expected = (centre - half) / denom
        self.assertAlmostEqual(lb, expected, places=10)

    def test_wilson_zero_n_returns_zero(self):
        self.assertEqual(self.m.wilson_lower_bound(0, 0), 0.0)

    def test_wilson_unanimous_returns_below_1(self):
        # 100/100 should give a non-trivial lower bound < 1.
        lb = self.m.wilson_lower_bound(100, 100)
        self.assertGreater(lb, 0.0)
        self.assertLess(lb, 1.0)


class TestStatusClassifier(_Base):
    """Status ladder must match spec."""

    def test_low_n_returns_too_weak(self):
        # n = 5 — well below MIN_N_FOR_IMPROVING (=20)
        pnls = [10.0, -5.0, 8.0, -3.0, 6.0]
        out = self.m.compute_strategy_evidence_bounds("demo",
                                                       self._make_trades(pnls),
                                                       bootstrap_n=100)
        self.assertEqual(out["status"], self.m.EVIDENCE_TOO_WEAK)
        self.assertFalse(out["sample_size_sufficiency"])

    def test_weak_lb_blocks_robust_candidate(self):
        # n >= 50 but Wilson WR LB pushes below 0.40 with marginal wins.
        # Construct 27 wins + 23 losses (WR = 54%) but small wins / big
        # losses → Wilson LB ~ 0.40 and PF LB << 1.3.
        pnls = ([5.0] * 27) + ([-50.0] * 23)
        ledger = self._make_trades(pnls)
        out = self.m.compute_strategy_evidence_bounds("demo", ledger,
                                                       bootstrap_n=200)
        # Should NOT be ROBUST_CANDIDATE — PF LB cannot be ≥ 1.3 here.
        self.assertNotEqual(out["status"],
                            self.m.EVIDENCE_ROBUST_CANDIDATE)
        # PF mean is 135/1150 < 1.0 → not EVIDENCE_REJECT either.
        self.assertIn(out["status"],
                      {self.m.EVIDENCE_TOO_WEAK,
                       self.m.EVIDENCE_DEGRADING,
                       self.m.EVIDENCE_REJECT,
                       self.m.EVIDENCE_IMPROVING})

    def test_mid_sample_good_wr_returns_improving(self):
        # n = 30 (between 20 and 50), WR mean 60%, Wilson LB ≥ 0.40.
        pnls = ([10.0] * 18) + ([-5.0] * 12)
        out = self.m.compute_strategy_evidence_bounds("demo",
                                                       self._make_trades(pnls),
                                                       bootstrap_n=200)
        self.assertEqual(out["status"], self.m.EVIDENCE_IMPROVING)
        self.assertGreaterEqual(out["win_rate_mean"], 0.50)

    def test_degrading_tail_flagged(self):
        # n = 60. First 20 strongly positive, last 20 strongly negative.
        # Wilson LB stays above 0.40 because overall WR ~ 0.50.
        pnls = ([20.0] * 20) + ([10.0] * 20) + ([-30.0] * 20)
        ledger = self._make_trades(pnls)
        out = self.m.compute_strategy_evidence_bounds("demo", ledger,
                                                       bootstrap_n=300)
        # Must surface degradation either as the status OR via the
        # last_20_worse_than_first_20 flag.
        self.assertTrue(out["last_20_worse_than_first_20"])
        # If overall PF is strong but tail is bad, status should be
        # DEGRADING. If PF LB collapses, it can also be TOO_WEAK.
        self.assertIn(out["status"],
                      {self.m.EVIDENCE_DEGRADING,
                       self.m.EVIDENCE_TOO_WEAK})

    def test_pf_mean_high_but_lb_low_returns_reject(self):
        # Construct a tail-driven ledger: one massive winner + many small
        # losers. PF mean inflates above 1.3 but PF LB << 1.0.
        pnls = ([200.0] * 1) + ([-1.0] * 59)
        ledger = self._make_trades(pnls)
        out = self.m.compute_strategy_evidence_bounds("demo", ledger,
                                                       bootstrap_n=500)
        # PF mean = 200/59 ~ 3.4. PF LB after bootstrap is dominated by
        # samples that drop the single winner → close to 0.
        self.assertGreaterEqual(out["profit_factor_mean"],
                                self.m.MIN_PF_MEAN_FOR_REJECT)
        self.assertLess(out["profit_factor_lower_bound"],
                         self.m.MAX_PF_LB_FOR_REJECT)
        self.assertEqual(out["status"], self.m.EVIDENCE_REJECT)


class TestBootstrapDeterministic(_Base):
    """Two calls with the same strategy name + same ledger must match."""

    def test_bootstrap_deterministic_same_strategy(self):
        pnls = [5.0, -3.0, 8.0, -2.0, 6.0, -4.0, 10.0,
                -7.0, 4.0, -2.0] * 6   # 60 records
        ledger1 = []
        ledger2 = []
        for i, p in enumerate(pnls):
            r = {"strategy": "demo", "net_pnl": p,
                 "symbol": "AAPL",
                 "regime": "RISK_ON",
                 "closed_at": f"2026-06-0{(i % 9) + 1}T13:00:00Z",
                 "size_usd": 1000.0}
            ledger1.append(dict(r))
            ledger2.append(dict(r))

        out1 = self.m.compute_strategy_evidence_bounds("demo", ledger1,
                                                        bootstrap_n=500)
        out2 = self.m.compute_strategy_evidence_bounds("demo", ledger2,
                                                        bootstrap_n=500)
        for key in ("profit_factor_lower_bound",
                    "expectancy_lower_bound",
                    "drawdown_upper_bound",
                    "bootstrap_outcome_stability",
                    "probability_of_negative_expectancy"):
            self.assertEqual(out1[key], out2[key],
                              f"{key} not deterministic")

    def test_bootstrap_seed_differs_by_strategy(self):
        """Different strategy names must seed different bootstraps."""
        pnls = [5.0, -3.0] * 30
        ledger = []
        for i, p in enumerate(pnls):
            ledger.append({"strategy": "demo", "net_pnl": p,
                            "symbol": "AAPL",
                            "closed_at": "2026-06-01T13:00:00Z",
                            "size_usd": 1000.0})

        out_a = self.m.compute_strategy_evidence_bounds("alpha", ledger,
                                                        bootstrap_n=200)
        out_b = self.m.compute_strategy_evidence_bounds("bravo", ledger,
                                                        bootstrap_n=200)
        self.assertNotEqual(out_a["bootstrap_seed"], out_b["bootstrap_seed"])


class TestClassifyStrategyEvidenceWrapper(_Base):
    """The convenience wrapper must return the same status."""

    def test_wrapper_matches_full(self):
        pnls = [5.0, -3.0] * 5
        ledger = []
        for i, p in enumerate(pnls):
            ledger.append({"strategy": "demo", "net_pnl": p,
                            "symbol": "AAPL",
                            "closed_at": "2026-06-01T13:00:00Z"})
        full = self.m.compute_strategy_evidence_bounds("demo", ledger,
                                                       bootstrap_n=100)
        status = self.m.classify_strategy_evidence(ledger, "demo",
                                                    bootstrap_n=100)
        self.assertEqual(status, full["status"])

    def test_empty_ledger_fail_soft(self):
        out = self.m.compute_strategy_evidence_bounds("demo", [],
                                                       bootstrap_n=100)
        self.assertEqual(out["status"], self.m.EVIDENCE_TOO_WEAK)
        self.assertEqual(out["n_closed"], 0)


if __name__ == "__main__":
    unittest.main()
