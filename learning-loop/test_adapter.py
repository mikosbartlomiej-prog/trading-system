"""
Baseline test suite for learning-loop/adapter.py

This is the CI gate for Lane 2 auto-PR: when the LLM proposes a new
heuristic and the routine opens a PR adding it to adapter.py, these
tests must stay green for the auto-merge gate to fire (or for human
review to be confident no regression).

Tests cover the 6 documented heuristics from STRATEGY.md §5.6:
  1. Insufficient sample (< MIN_SAMPLE_TRADES) -> hold
  2. Win-rate cool-down (< 35% over 5+ trades) -> size *= 0.8
  3. Win-rate warm-up (> 60% over 5+ trades) -> size *= 1.10
  4. P&L cool-down (< -2% equity 7d) -> size *= 0.7
  5. P&L warm-up (> +3% equity 7d) -> size *= 1.05
  6. Consecutive losses limit (5+) -> pause for 3 days
  7. Lifetime ROI disable (< -10%) -> permanent disable
  8. Options side-bias from long-vs-short P&L split
  9. Bounds: 0.30 <= size_multiplier <= 2.00
 10. Pause auto-resume after PAUSE_DAYS

When LLM adds a new heuristic, test author should also add the
matching test case here. Routine system prompt instructs the LLM to
include test_addition alongside code_patch.
"""

import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

# Make adapter importable regardless of CWD
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from adapter import (  # noqa: E402
    adapt, adapt_strategy,
    MIN_SAMPLE_TRADES, MIN_7D_TRADES,
    MIN_SIZE_MULT, MAX_SIZE_MULT,
    WR_COOL_THRESHOLD, WR_WARM_THRESHOLD,
    PL_COOL_PCT, PL_WARM_PCT,
    CONSECUTIVE_LOSS_LIMIT, LIFETIME_ROI_DISABLE_PCT,
    PAUSE_DAYS,
)

EQUITY = 100_000.0


def _stats(**kw) -> dict:
    """Build a per-strategy stats dict with sensible defaults."""
    base = {
        "trades_lifetime":   20,
        "trades_7d":         10,
        "win_rate_lifetime": 0.50,
        "win_rate_7d":       0.50,
        "pnl_usd_lifetime":  0.0,
        "pnl_usd_7d":        0.0,
        "consecutive_losses": 0,
        "pnl_long_7d":       0.0,
        "pnl_short_7d":      0.0,
        "starting_equity":   EQUITY,
    }
    base.update(kw)
    return base


# ─── Heuristic-level tests (adapt_strategy) ──────────────────────────────────

class TestInsufficientSample(unittest.TestCase):
    def test_hold_below_min_lifetime(self):
        old = {"size_multiplier": 1.0, "enabled": True}
        stats = _stats(trades_lifetime=MIN_SAMPLE_TRADES - 1, win_rate_7d=0.20)
        new = adapt_strategy("momentum-long", old, stats, EQUITY)
        # No size change despite cold win rate
        self.assertEqual(new["size_multiplier"], 1.0)
        self.assertIn("hold", new["rationale"])


class TestWinRateThresholds(unittest.TestCase):
    def test_cool_down_at_low_win_rate(self):
        old = {"size_multiplier": 1.0, "enabled": True}
        stats = _stats(trades_lifetime=20, trades_7d=10, win_rate_7d=0.20)
        new = adapt_strategy("momentum-long", old, stats, EQUITY)
        self.assertAlmostEqual(new["size_multiplier"], 0.8, places=2)

    def test_warm_up_at_high_win_rate(self):
        old = {"size_multiplier": 1.0, "enabled": True}
        stats = _stats(trades_lifetime=20, trades_7d=10, win_rate_7d=0.83)
        new = adapt_strategy("momentum-long", old, stats, EQUITY)
        self.assertAlmostEqual(new["size_multiplier"], 1.10, places=2)

    def test_no_change_in_neutral_zone(self):
        old = {"size_multiplier": 1.0, "enabled": True}
        stats = _stats(trades_lifetime=20, trades_7d=10, win_rate_7d=0.50)
        new = adapt_strategy("momentum-long", old, stats, EQUITY)
        self.assertAlmostEqual(new["size_multiplier"], 1.0, places=2)

    def test_skip_when_7d_sample_too_small(self):
        old = {"size_multiplier": 1.0, "enabled": True}
        stats = _stats(trades_lifetime=20, trades_7d=MIN_7D_TRADES - 1, win_rate_7d=0.20)
        new = adapt_strategy("momentum-long", old, stats, EQUITY)
        self.assertEqual(new["size_multiplier"], 1.0)


class TestPLThresholds(unittest.TestCase):
    def test_cool_down_at_negative_pl(self):
        # 7d P&L = -3% equity -> below -2% threshold
        old = {"size_multiplier": 1.0, "enabled": True}
        stats = _stats(trades_lifetime=20, trades_7d=10,
                       win_rate_7d=0.50, pnl_usd_7d=-3000)
        new = adapt_strategy("momentum-long", old, stats, EQUITY)
        self.assertAlmostEqual(new["size_multiplier"], 0.7, places=2)

    def test_warm_up_at_positive_pl(self):
        # 7d P&L = +5% equity -> above +3% threshold
        old = {"size_multiplier": 1.0, "enabled": True}
        stats = _stats(trades_lifetime=20, trades_7d=10,
                       win_rate_7d=0.50, pnl_usd_7d=5000)
        new = adapt_strategy("momentum-long", old, stats, EQUITY)
        self.assertAlmostEqual(new["size_multiplier"], 1.05, places=2)


class TestConsecutiveLossesPause(unittest.TestCase):
    def test_pause_at_5_consecutive(self):
        old = {"size_multiplier": 1.0, "enabled": True}
        stats = _stats(trades_lifetime=20, trades_7d=10,
                       consecutive_losses=CONSECUTIVE_LOSS_LIMIT)
        new = adapt_strategy("momentum-long", old, stats, EQUITY)
        self.assertFalse(new["enabled"])
        self.assertIsNotNone(new["paused_until"])
        # Paused exactly PAUSE_DAYS into the future
        until = datetime.fromisoformat(new["paused_until"]).date()
        expected = (datetime.now(timezone.utc).date() + timedelta(days=PAUSE_DAYS))
        self.assertEqual(until, expected)

    def test_no_pause_below_threshold(self):
        old = {"size_multiplier": 1.0, "enabled": True}
        stats = _stats(trades_lifetime=20, trades_7d=10,
                       consecutive_losses=CONSECUTIVE_LOSS_LIMIT - 1)
        new = adapt_strategy("momentum-long", old, stats, EQUITY)
        self.assertTrue(new["enabled"])

    def test_auto_resume_after_pause_expires(self):
        old = {
            "size_multiplier": 0.7,
            "enabled": False,
            "paused_until": (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat(),
        }
        stats = _stats(trades_lifetime=20, trades_7d=5,
                       consecutive_losses=0)
        new = adapt_strategy("momentum-long", old, stats, EQUITY)
        self.assertTrue(new["enabled"])
        self.assertIsNone(new["paused_until"])


class TestLifetimeROIDisable(unittest.TestCase):
    def test_disable_when_lifetime_roi_below_threshold(self):
        old = {"size_multiplier": 1.0, "enabled": True}
        # -15% lifetime ROI on $100k -> $-15k
        stats = _stats(trades_lifetime=20, trades_7d=10,
                       pnl_usd_lifetime=-15000, starting_equity=EQUITY)
        new = adapt_strategy("momentum-long", old, stats, EQUITY)
        self.assertFalse(new["enabled"])
        self.assertIn("DISABLED", new["rationale"])


class TestOptionsSideBias(unittest.TestCase):
    def test_short_bias_when_long_loses_short_wins(self):
        old = {"size_multiplier": 1.0, "enabled": True}
        stats = _stats(trades_lifetime=20, trades_7d=5,
                       win_rate_7d=0.40,
                       pnl_long_7d=-200, pnl_short_7d=300)
        new = adapt_strategy("options-momentum", old, stats, EQUITY)
        self.assertEqual(new["side_bias"], "short")

    def test_long_bias_when_short_loses_long_wins(self):
        old = {"size_multiplier": 1.0, "enabled": True}
        stats = _stats(trades_lifetime=20, trades_7d=5,
                       win_rate_7d=0.40,
                       pnl_long_7d=300, pnl_short_7d=-200)
        new = adapt_strategy("options-momentum", old, stats, EQUITY)
        self.assertEqual(new["side_bias"], "long")

    def test_no_bias_for_non_options_strategy(self):
        old = {"size_multiplier": 1.0, "enabled": True, "side_bias": None}
        stats = _stats(trades_lifetime=20, trades_7d=5,
                       pnl_long_7d=-200, pnl_short_7d=300)
        new = adapt_strategy("momentum-long", old, stats, EQUITY)
        self.assertIsNone(new["side_bias"])


class TestSizeBounds(unittest.TestCase):
    def test_size_clamped_to_max(self):
        # Already near MAX, warm-up shouldn't push past MAX
        old = {"size_multiplier": 1.95, "enabled": True}
        stats = _stats(trades_lifetime=20, trades_7d=10, win_rate_7d=0.83)
        new = adapt_strategy("momentum-long", old, stats, EQUITY)
        self.assertLessEqual(new["size_multiplier"], MAX_SIZE_MULT)

    def test_size_clamped_to_min(self):
        # Already near MIN, cool-down shouldn't push below MIN
        old = {"size_multiplier": 0.40, "enabled": True}
        stats = _stats(trades_lifetime=20, trades_7d=10, win_rate_7d=0.20)
        new = adapt_strategy("momentum-long", old, stats, EQUITY)
        self.assertGreaterEqual(new["size_multiplier"], MIN_SIZE_MULT)


# ─── Top-level orchestration tests (adapt) ───────────────────────────────────

class TestAdaptOrchestration(unittest.TestCase):
    def test_first_run_initializes_state(self):
        today_stats = {
            "as_of": "2026-05-08",
            "equity": EQUITY,
            "starting_equity": EQUITY,
            "by_strategy": {"momentum-long": _stats()},
            "by_asset_class": {"stocks": {}},
            "by_source": {},
            "cumulative_trades": 20,
            "cumulative_pnl_usd": 0.0,
        }
        new_state, rationale = adapt({}, today_stats)
        self.assertEqual(new_state["version"], "1.0")
        self.assertEqual(new_state["days_tracked"], 1)
        self.assertIn("momentum-long", new_state["strategies"])
        self.assertEqual(new_state["cumulative"]["total_trades"], 20)

    def test_no_changes_when_thresholds_quiet(self):
        old = {
            "version": "1.0", "days_tracked": 5,
            "cumulative": {"total_trades": 10, "total_pnl_usd": 0,
                            "starting_equity": EQUITY},
            "strategies": {
                "momentum-long": {"size_multiplier": 1.0, "enabled": True,
                                   "side_bias": None, "trades_lifetime": 20},
            },
        }
        today_stats = {
            "as_of": "2026-05-08",
            "equity": EQUITY,
            "starting_equity": EQUITY,
            "by_strategy": {"momentum-long": _stats(win_rate_7d=0.50)},
            "by_asset_class": {},
            "by_source": {},
            "cumulative_trades": 20,
            "cumulative_pnl_usd": 0.0,
        }
        new_state, rationale = adapt(old, today_stats)
        self.assertEqual(len(rationale), 1)
        self.assertIn("no parameter changes", rationale[0])

    def test_changes_emitted_in_rationale(self):
        old = {
            "version": "1.0", "days_tracked": 5,
            "cumulative": {"total_trades": 10, "total_pnl_usd": 0,
                            "starting_equity": EQUITY},
            "strategies": {
                "momentum-long": {"size_multiplier": 1.0, "enabled": True,
                                   "side_bias": None, "trades_lifetime": 20},
            },
        }
        today_stats = {
            "as_of": "2026-05-08",
            "equity": EQUITY,
            "starting_equity": EQUITY,
            "by_strategy": {"momentum-long": _stats(win_rate_7d=0.83)},
            "by_asset_class": {},
            "by_source": {},
            "cumulative_trades": 20,
            "cumulative_pnl_usd": 0.0,
        }
        new_state, rationale = adapt(old, today_stats)
        # We expect a size_multiplier change line
        self.assertTrue(any("size_multiplier 1.00 -> 1.10" in r for r in rationale),
                        f"rationale: {rationale}")


if __name__ == "__main__":
    unittest.main()


# ─── Lane2 auto-added test for: Detect options-momentum fill rate below 50% over 5+ orders and alert to widen limits ─────
# Auto-injected by lane2_pr to expose new symbols to the test:
from adapter import heuristic_options_limit_too_tight  # noqa: E402,F401


class TestOptionsLimitTooTight(unittest.TestCase):
    def test_triggers_on_low_fill_with_sufficient_sample(self):
        fill_stats = {"options-momentum": {"placed": 10, "fill_rate": 0.4}}
        fired, reason = heuristic_options_limit_too_tight(fill_stats)
        self.assertTrue(fired)
        self.assertIn("limits too tight", reason)
    def test_no_trigger_below_min_sample(self):
        fill_stats = {"options-momentum": {"placed": 3, "fill_rate": 0.2}}
        fired, _ = heuristic_options_limit_too_tight(fill_stats)
        self.assertFalse(fired)
    def test_no_trigger_acceptable_fill_rate(self):
        fill_stats = {"options-momentum": {"placed": 10, "fill_rate": 0.65}}
        fired, _ = heuristic_options_limit_too_tight(fill_stats)
        self.assertFalse(fired)
    def test_no_trigger_missing_strategy_key(self):
        fired, _ = heuristic_options_limit_too_tight({})
        self.assertFalse(fired)


# ─── SPY-overbought regime gate tests (Lane 2 PR #4, 2026-05-14) ────────────
from adapter import heuristic_spy_overbought_options_block  # noqa: E402,F401


class TestSpyOverboughtOptionsBlock(unittest.TestCase):
    def test_blocks_at_rsi_82(self):
        stats = {"rsi_snapshot": {"SPY": {"today": 82.4}}}
        fired, reason = heuristic_spy_overbought_options_block(stats)
        self.assertTrue(fired)
        self.assertIn("82.4", reason)

    def test_no_block_at_rsi_70(self):
        stats = {"rsi_snapshot": {"SPY": {"today": 70.0}}}
        fired, _ = heuristic_spy_overbought_options_block(stats)
        self.assertFalse(fired)

    def test_blocks_just_above_threshold(self):
        stats = {"rsi_snapshot": {"SPY": {"today": 75.1}}}
        fired, _ = heuristic_spy_overbought_options_block(stats)
        self.assertTrue(fired)

    def test_no_block_at_threshold(self):
        stats = {"rsi_snapshot": {"SPY": {"today": 75.0}}}
        fired, _ = heuristic_spy_overbought_options_block(stats)
        self.assertFalse(fired)

    def test_no_block_missing_spy_data(self):
        fired, _ = heuristic_spy_overbought_options_block({})
        self.assertFalse(fired)

    def test_no_block_spy_rsi_none(self):
        stats = {"rsi_snapshot": {"SPY": {}}}
        fired, _ = heuristic_spy_overbought_options_block(stats)
        self.assertFalse(fired)
