"""backtest realism — slippage, gap penalty, missed runs, rich metrics."""
import os
import sys
import unittest

import os, sys; sys.path.insert(0, os.path.dirname(__file__)); import _path  # noqa: F401

# backtest is a package — add its parent (REPO_ROOT) so `import backtest.realism` works
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from backtest.realism import (
    RealismConfig,
    apply_entry_slippage, apply_exit_slippage,
    gap_penalty, should_skip_run, compute_rich_metrics,
    replay_with_realism,
)


class TestSlippage(unittest.TestCase):
    def test_long_entry_worsened(self):
        cfg = RealismConfig(slippage_bps=10.0)
        # 10bps = 0.1%. Long pays 100.1 to enter 100.
        self.assertAlmostEqual(apply_entry_slippage(100, "long", cfg), 100.10)

    def test_short_entry_worsened(self):
        cfg = RealismConfig(slippage_bps=10.0)
        # Short receives 99.9 (sells at lower price than expected)
        self.assertAlmostEqual(apply_entry_slippage(100, "short", cfg), 99.90)

    def test_long_exit_worsened(self):
        cfg = RealismConfig(slippage_bps=10.0)
        # Long sells at 99.9 instead of 100.
        self.assertAlmostEqual(apply_exit_slippage(100, "long", cfg), 99.90)

    def test_crypto_higher_slippage(self):
        cfg = RealismConfig(slippage_bps=10.0, slippage_bps_crypto=50.0)
        self.assertGreater(
            abs(apply_entry_slippage(100, "long", cfg, "crypto") - 100),
            abs(apply_entry_slippage(100, "long", cfg, "us_equity") - 100),
        )

    def test_options_higher_slippage_than_crypto(self):
        cfg = RealismConfig(slippage_bps_crypto=20, slippage_bps_options=80)
        self.assertGreater(
            abs(apply_entry_slippage(1.0, "long", cfg, "us_option") - 1.0),
            abs(apply_entry_slippage(1.0, "long", cfg, "crypto") - 1.0),
        )


class TestGapPenalty(unittest.TestCase):
    def test_long_stop_filled_below(self):
        cfg = RealismConfig(gap_penalty_pct=0.01)  # 1% gap
        # SL at 95 fills at 94.05 for a long
        self.assertAlmostEqual(gap_penalty(95, "long", cfg), 94.05)

    def test_short_stop_filled_above(self):
        cfg = RealismConfig(gap_penalty_pct=0.01)
        self.assertAlmostEqual(gap_penalty(105, "short", cfg), 106.05)


class TestMissedRuns(unittest.TestCase):
    def test_zero_pct_never_skips(self):
        cfg = RealismConfig(missed_run_pct=0.0)
        self.assertFalse(any(should_skip_run(i, cfg) for i in range(100)))

    def test_full_pct_always_skips(self):
        cfg = RealismConfig(missed_run_pct=1.0)
        self.assertTrue(all(should_skip_run(i, cfg) for i in range(100)))

    def test_partial_deterministic(self):
        cfg_a = RealismConfig(missed_run_pct=0.3, seed=42)
        cfg_b = RealismConfig(missed_run_pct=0.3, seed=42)
        cfg_c = RealismConfig(missed_run_pct=0.3, seed=43)
        a = [should_skip_run(i, cfg_a) for i in range(50)]
        b = [should_skip_run(i, cfg_b) for i in range(50)]
        c = [should_skip_run(i, cfg_c) for i in range(50)]
        self.assertEqual(a, b)             # same seed → same outcomes
        self.assertNotEqual(a, c)          # different seed → different
        skip_pct = sum(a) / 50
        # Roughly around 0.3 — accept wide tolerance for small sample
        self.assertGreater(skip_pct, 0.05)
        self.assertLess(skip_pct, 0.6)


class TestRichMetrics(unittest.TestCase):
    def _trades(self):
        return [
            {"pnl_usd": 100, "pnl_pct": 1.0, "hold_days": 3, "exit_reason": "TP", "winner": True, "filled": True},
            {"pnl_usd": -50, "pnl_pct": -0.5, "hold_days": 5, "exit_reason": "SL", "winner": False, "filled": True},
            {"pnl_usd":  80, "pnl_pct": 0.8, "hold_days": 4, "exit_reason": "TP", "winner": True, "filled": True},
            {"pnl_usd": -30, "pnl_pct": -0.3, "hold_days": 2, "exit_reason": "SL", "winner": False, "filled": True},
        ]

    def test_basic_metrics(self):
        m = compute_rich_metrics(self._trades())
        self.assertEqual(m["n_trades"], 4)
        self.assertEqual(m["wins"], 2)
        self.assertEqual(m["losses"], 2)
        self.assertEqual(m["total_pnl_usd"], 100)

    def test_profit_factor(self):
        m = compute_rich_metrics(self._trades())
        # win sum = 180, loss sum = -80 → PF = 2.25
        self.assertAlmostEqual(m["profit_factor"], 2.25, places=2)

    def test_tp_hit_rate(self):
        m = compute_rich_metrics(self._trades())
        self.assertEqual(m["tp_hit_rate"], 0.5)

    def test_empty_trades(self):
        m = compute_rich_metrics([])
        self.assertEqual(m["n_trades"], 0)
        self.assertEqual(m["profit_factor"], 0.0)


class TestReplayMonotonicity(unittest.TestCase):
    """Realism only ever makes outcomes WORSE (slippage + costs cannot
    help). Same signal stream → realistic total_pnl <= naive total_pnl."""

    def _synthetic_bars(self):
        # 40 days of clean uptrend with one breakout
        closes = [100.0 + i * 0.5 for i in range(40)]
        return {
            "time":  [f"2026-01-{(i % 28) + 1:02d}" for i in range(40)],
            "open":  closes,
            "high":  [c * 1.01 for c in closes],
            "low":   [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000] * 40,
        }

    def _signal(self, idx, bars):
        # Buy on day 10, target 5% TP, 2% SL
        if idx != 10:
            return None
        entry = bars["close"][idx]
        return {
            "action": "BUY", "strategy": "test",
            "entry_price": entry, "stop_loss": entry * 0.98,
            "take_profit": entry * 1.05,
        }

    def test_realism_worsens_pnl(self):
        bars = self._synthetic_bars()
        no_slip = RealismConfig(slippage_bps=0, gap_penalty_pct=0, cost_per_trade_usd=0)
        full_slip = RealismConfig(slippage_bps=50, gap_penalty_pct=0.02, cost_per_trade_usd=5)

        clean = replay_with_realism(bars, self._signal, ticker="X", config=no_slip)
        dirty = replay_with_realism(bars, self._signal, ticker="X", config=full_slip)

        clean_pnl = clean["summary"]["total_pnl_usd"]
        dirty_pnl = dirty["summary"]["total_pnl_usd"]
        # Both should have placed the trade
        self.assertEqual(clean["summary"]["n_trades"], 1)
        self.assertEqual(dirty["summary"]["n_trades"], 1)
        self.assertGreaterEqual(clean_pnl, dirty_pnl)


if __name__ == "__main__":
    unittest.main()
