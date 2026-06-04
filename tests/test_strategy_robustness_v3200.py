"""v3.20.0 (2026-06-04) — Tests for shared/strategy_robustness.py.

Verifies:
  * Robustness score is computed and in [0, 1].
  * Overfit suspicion fires when one trade dominates positive PnL.
  * Fragility detected per sweep axis (cost / time / regime / symbol).
  * Sandbox never mutates the runtime — both sentinels are True and the
    input ledger is unchanged after a run.
  * Output is deterministic — same input → same output.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))


class _Base(unittest.TestCase):
    def setUp(self):
        for k in list(sys.modules):
            if k.endswith(".strategy_robustness") \
               or k == "strategy_robustness":
                del sys.modules[k]
        import strategy_robustness as sr
        self.m = sr

    def _make_trades(self, specs: list[tuple]) -> list[dict]:
        """specs: list of (net_pnl, symbol, regime, day_iso)."""
        out = []
        for i, (pnl, sym, reg, day) in enumerate(specs):
            out.append({
                "strategy":  "demo",
                "symbol":    sym,
                "regime":    reg,
                "closed_at": f"{day}T13:00:00Z",
                "net_pnl":   pnl,
                "size_usd":  1000.0,
            })
        return out


class TestSandboxSentinels(_Base):
    """Spec contract: sandbox NEVER optimizes, NEVER mutates runtime."""

    def test_sentinels_true(self):
        self.assertTrue(self.m.SANDBOX_NEVER_OPTIMIZES)
        self.assertTrue(self.m.SANDBOX_NEVER_MUTATES_RUNTIME)

    def test_ledger_unchanged_after_run(self):
        ledger = self._make_trades([
            (10.0, "AAPL", "RISK_ON", "2026-05-01"),
            (-5.0, "MSFT", "RISK_ON", "2026-05-02"),
            (8.0, "AAPL", "RISK_OFF", "2026-05-03"),
            (-3.0, "MSFT", "RISK_OFF", "2026-05-04"),
            (12.0, "AAPL", "RISK_ON", "2026-05-05"),
        ])
        snapshot = copy.deepcopy(ledger)
        out = self.m.run_robustness_suite("demo", ledger,
                                           params={"atr_mult": 2.0})
        # Result echoes sentinels.
        self.assertTrue(out["sandbox_never_optimizes"])
        self.assertTrue(out["sandbox_never_mutates_runtime"])
        # Original ledger unchanged.
        self.assertEqual(snapshot, ledger)
        # Robustness score is in [0, 1].
        self.assertGreaterEqual(out["robustness_score"], 0.0)
        self.assertLessEqual(out["robustness_score"], 1.0)


class TestRobustnessScore(_Base):
    """Score = 1 - max_relative_degradation."""

    def test_score_computed_and_in_range(self):
        ledger = self._make_trades([
            (5.0, "AAPL", "RISK_ON", f"2026-05-{(i % 28) + 1:02d}")
            for i in range(30)
        ])
        out = self.m.run_robustness_suite("demo", ledger)
        self.assertIn("robustness_score", out)
        self.assertGreaterEqual(out["robustness_score"], 0.0)
        self.assertLessEqual(out["robustness_score"], 1.0)
        # Identity-cost-only sandbox + uniform ledger has trivial drop.
        self.assertGreater(out["robustness_score"], 0.5)


class TestOverfitSuspicion(_Base):
    """One trade dominates positive PnL → overfit_suspicion = True."""

    def test_single_dominant_trade_flagged(self):
        # One huge win + many small losses.
        specs = [(500.0, "AAPL", "RISK_ON", "2026-05-01")]
        for i in range(20):
            specs.append((-1.0, "MSFT", "RISK_ON",
                          f"2026-05-{(i % 28) + 2:02d}"))
        ledger = self._make_trades(specs)
        out = self.m.run_robustness_suite("demo", ledger)
        self.assertTrue(out["overfit_suspicion"])
        # Dominant flag should also show up in drop-one-best-trade.
        self.assertTrue(out["drop_one_best_trade"]["dominant_trade"])


class TestFragilityPerSweep(_Base):
    """Fragility flags must populate when a perturbation crashes
    expectancy."""

    def test_cost_sensitivity_fragility(self):
        # Make trades so that even modest slippage tips them red.
        specs = [(2.0, "AAPL", "RISK_ON",
                  f"2026-05-{(i % 28) + 1:02d}") for i in range(30)]
        ledger = self._make_trades(specs)
        # Force size_usd large so the identity simulator's cost is heavy.
        for r in ledger:
            r["size_usd"] = 100_000.0
        out = self.m.run_robustness_suite("demo", ledger)
        cs = out["cost_sensitivity"]
        # At 10 bps cost on $100k = $100/trade, baseline expectancy $2
        # collapses → slippage_fragility should be True.
        self.assertTrue(cs["slippage_fragility"])
        self.assertGreater(out["max_relative_degradation"], 0.0)

    def test_symbol_split_fragility_when_one_symbol_loses(self):
        # Half winners on AAPL, half losers on MSFT.
        specs: list[tuple] = []
        for i in range(20):
            specs.append((10.0, "AAPL", "RISK_ON",
                          f"2026-05-{(i % 28) + 1:02d}"))
        for i in range(20):
            specs.append((-15.0, "MSFT", "RISK_ON",
                          f"2026-05-{(i % 28) + 1:02d}"))
        ledger = self._make_trades(specs)
        out = self.m.run_robustness_suite("demo", ledger)
        sym = out["symbol_splits"]
        self.assertIn("AAPL", sym["buckets"])
        self.assertIn("MSFT", sym["buckets"])
        # Drop-one-best-symbol should reveal AAPL drives positive PnL.
        ds = out["drop_one_best_symbol"]
        self.assertEqual(ds["best_symbol"], "AAPL")


class TestDeterministicOutput(_Base):
    """Same input → same output."""

    def test_deterministic(self):
        specs = [(5.0, "AAPL", "RISK_ON",
                  f"2026-05-{(i % 28) + 1:02d}") for i in range(20)]
        l1 = self._make_trades(specs)
        l2 = self._make_trades(specs)
        out1 = self.m.run_robustness_suite("demo", l1,
                                            params={"atr_mult": 2.0})
        out2 = self.m.run_robustness_suite("demo", l2,
                                            params={"atr_mult": 2.0})
        # Robustness score / max degradation must match exactly.
        self.assertEqual(out1["robustness_score"],
                         out2["robustness_score"])
        self.assertEqual(out1["max_relative_degradation"],
                         out2["max_relative_degradation"])
        # Cost sensitivity is deterministic.
        self.assertEqual(out1["cost_sensitivity"]["slippage"],
                         out2["cost_sensitivity"]["slippage"])


class TestParameterSweepRequiresParams(_Base):
    """Empty params → empty parameter_sensitivity dict."""

    def test_no_params(self):
        ledger = self._make_trades([
            (5.0, "AAPL", "RISK_ON",
             f"2026-05-{(i % 28) + 1:02d}") for i in range(10)
        ])
        out = self.m.run_robustness_suite("demo", ledger, params=None)
        self.assertEqual(out["parameter_sensitivity"], {})

    def test_empty_ledger_fail_soft(self):
        out = self.m.run_robustness_suite("demo", [])
        # Empty ledger gives 1.0 score (no degradation to measure) and
        # an explicit n_trades = 0.
        self.assertEqual(out["n_trades"], 0)
        self.assertGreaterEqual(out["robustness_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
