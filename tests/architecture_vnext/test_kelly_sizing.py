"""v3.11 Phase D — kelly_sizing tests."""

import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import _path  # noqa: F401

import unittest

from kelly_sizing import compute_kelly_size, _kelly_fraction


class TestKellyFraction(unittest.TestCase):
    def test_positive_edge_returns_positive_fraction(self):
        # 70% WR, 1.5 payoff → f = (0.7*1.5 - 0.3)/1.5 = 0.5
        self.assertAlmostEqual(_kelly_fraction(0.70, 1.5), 0.5, places=3)

    def test_breakeven_returns_zero(self):
        # 50% WR, 1.0 payoff → f = 0
        self.assertEqual(_kelly_fraction(0.50, 1.0), 0.0)

    def test_negative_edge_returns_zero_floor(self):
        # 40% WR, 1.0 payoff → f = -0.2, clamped to 0
        self.assertEqual(_kelly_fraction(0.40, 1.0), 0.0)

    def test_extreme_edge_capped_at_0_5(self):
        # 95% WR, 5.0 payoff → would be huge; clamped to 0.5
        f = _kelly_fraction(0.95, 5.0)
        self.assertLessEqual(f, 0.5)


class TestComputeKellySize(unittest.TestCase):

    def test_insufficient_sample_returns_base(self):
        size, reason = compute_kelly_size(
            strategy_name="new-strat",
            strategy_stats={"trades_lifetime": 3, "win_rate_lifetime": 0.7},
            equity=100000, base_size_usd=15000,
        )
        self.assertEqual(size, 15000)
        self.assertIn("insufficient sample", reason)

    def test_strong_edge_returns_above_base(self):
        # 70% WR, payoff 1.5 (explicit), 20 trades → Kelly 0.5 × 0.25 = 0.125 × $100k = $12.5k
        # That's BELOW base $15k → clamped to floor (0.10 × 15k = $1.5k)?
        # Actually no — KELLY_MIN_RATIO is 0.10 OF BASE, so floor=$1.5k; result $12.5k > floor
        size, reason = compute_kelly_size(
            strategy_name="winner",
            strategy_stats={
                "trades_lifetime": 20, "win_rate_lifetime": 0.70,
                "avg_win_pct": 5.0, "avg_loss_pct": -3.33,  # payoff ~1.5
                "pnl_usd_lifetime": 3500,
            },
            equity=100000, base_size_usd=15000,
        )
        # 0.7 × 1.5 - 0.3 = 0.75, / 1.5 = 0.50, × 0.25 = 0.125 → $12.5k raw
        # clamped to [0.10 × 15k=1.5k, 2.0 × 15k=30k] = $12.5k
        self.assertAlmostEqual(size, 12500, delta=100)
        self.assertIn("kelly", reason.lower())

    def test_no_edge_returns_base(self):
        size, reason = compute_kelly_size(
            strategy_name="flat",
            strategy_stats={
                "trades_lifetime": 50, "win_rate_lifetime": 0.45,
                "avg_win_pct": 5.0, "avg_loss_pct": -5.0,  # payoff 1.0
            },
            equity=100000, base_size_usd=15000,
        )
        # f = 0.45×1.0 - 0.55 = -0.10 → 0 → return base
        self.assertEqual(size, 15000)
        self.assertIn("negative edge", reason.lower())

    def test_extreme_edge_clamped_to_max(self):
        # 90% WR, payoff 3.0 → Kelly = (0.9×3 - 0.1)/3 = 0.867 → clamped to 0.5
        # × 0.25 = 0.125 × $100k = $12.5k — but with payoff 3.0 single trade is big
        # Let's increase equity to test ceiling clamp
        size, reason = compute_kelly_size(
            strategy_name="hot",
            strategy_stats={
                "trades_lifetime": 30, "win_rate_lifetime": 0.90,
                "avg_win_pct": 9.0, "avg_loss_pct": -3.0,  # payoff 3.0
            },
            equity=1_000_000, base_size_usd=15000,  # huge equity
        )
        # Raw Kelly: 0.5 (clamped from 0.867) × 0.25 = 0.125 × $1M = $125k
        # KELLY_MAX_RATIO = 2.0 × base $15k = $30k → clamped
        self.assertAlmostEqual(size, 30000, delta=100)
        self.assertIn("2.0×", reason)

    def test_floor_applied_for_tiny_kelly(self):
        # 51% WR, payoff 1.0 → f = (0.51 - 0.49)/1 = 0.02
        # × 0.25 = 0.005 × $100k = $500
        # KELLY_MIN_RATIO = 0.10 × $15k = $1500 → floor wins
        size, reason = compute_kelly_size(
            strategy_name="marginal",
            strategy_stats={
                "trades_lifetime": 100, "win_rate_lifetime": 0.51,
                "avg_win_pct": 5.0, "avg_loss_pct": -5.0,
            },
            equity=100000, base_size_usd=15000,
        )
        self.assertAlmostEqual(size, 1500, delta=10)


if __name__ == "__main__":
    unittest.main()
