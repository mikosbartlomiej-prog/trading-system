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


# ─── Stale-exit-emergency tests (Lane 2 PR #3, 2026-05-09) ───────────────────
from adapter import heuristic_stale_exit_emergency  # noqa: E402,F401


class TestStaleExitEmergency(unittest.TestCase):
    def test_triggers_on_stale_pattern(self):
        stats = {"exit-emergency": {"placed": 4, "filled": 0, "canceled": 0}}
        fired, reason = heuristic_stale_exit_emergency(stats)
        self.assertTrue(fired)
        self.assertIn("stale LIMIT orders suspected", reason)

    def test_no_trigger_when_orders_canceled(self):
        stats = {"exit-emergency": {"placed": 4, "filled": 0, "canceled": 4}}
        fired, _ = heuristic_stale_exit_emergency(stats)
        self.assertFalse(fired)

    def test_no_trigger_below_min_placed(self):
        stats = {"exit-emergency": {"placed": 1, "filled": 0, "canceled": 0}}
        fired, _ = heuristic_stale_exit_emergency(stats)
        self.assertFalse(fired)

    def test_no_trigger_when_some_filled(self):
        stats = {"exit-emergency": {"placed": 4, "filled": 1, "canceled": 0}}
        fired, _ = heuristic_stale_exit_emergency(stats)
        self.assertFalse(fired)

    def test_no_trigger_missing_key(self):
        fired, _ = heuristic_stale_exit_emergency({})
        self.assertFalse(fired)


# ─── Lane2 auto-added test for: Crypto oversold bounce boost — ETH RSI ≤ 30 + BTC RSI ≤ 45 ─────
# Auto-injected by lane2_pr to expose new symbols to the test:
from adapter import heuristic_crypto_oversold_boost  # noqa: E402,F401

class TestCryptoOversoldBoost(unittest.TestCase):
    def test_fires_eth_oversold_btc_approaching(self):
        stats = {"rsi_snapshot": {"ETH/USD": {"today": 28.5}, "BTC/USD": {"today": 40.0}}}
        fired, mult, reason = heuristic_crypto_oversold_boost(stats)
        self.assertTrue(fired)
        self.assertAlmostEqual(mult, 1.3)
        self.assertIn("28.5", reason)
    def test_no_fire_eth_above_threshold(self):
        stats = {"rsi_snapshot": {"ETH/USD": {"today": 32.0}, "BTC/USD": {"today": 40.0}}}
        fired, _, _ = heuristic_crypto_oversold_boost(stats)
        self.assertFalse(fired)
    def test_no_fire_btc_above_threshold(self):
        stats = {"rsi_snapshot": {"ETH/USD": {"today": 28.0}, "BTC/USD": {"today": 50.0}}}
        fired, _, _ = heuristic_crypto_oversold_boost(stats)
        self.assertFalse(fired)
    def test_boundary_values_fire(self):
        stats = {"rsi_snapshot": {"ETH/USD": {"today": 30.0}, "BTC/USD": {"today": 45.0}}}
        fired, mult, _ = heuristic_crypto_oversold_boost(stats)
        self.assertTrue(fired)
        self.assertAlmostEqual(mult, 1.3)
    def test_missing_rsi_snapshot(self):
        fired, mult, _ = heuristic_crypto_oversold_boost({})
        self.assertFalse(fired)
        self.assertAlmostEqual(mult, 1.0)


# ─── PR #8 wire-in integration test (2026-05-22) ──────────────────────────
# Verifies that heuristic_crypto_oversold_boost is actually applied in
# adapt() loop, not just defined as standalone function.

from adapter import adapt  # noqa: E402


class TestCryptoOversoldBoostWiredIntoAdapt(unittest.TestCase):
    def _base_stats(self, rsi_snapshot):
        return {
            "as_of":            "2026-05-22",
            "equity":           95000.0,
            "starting_equity":  95000.0,
            "by_strategy": {
                "crypto-momentum": {
                    "trades_7d":         0,
                    "trades_lifetime":   0,
                    "win_rate_7d":       0.0,
                    "win_rate_lifetime": 0.0,
                    "pnl_usd_7d":        0.0,
                    "pnl_usd_lifetime":  0.0,
                    "consecutive_losses": 0,
                },
            },
            "by_asset_class": {},
            "by_source":      {},
            "rsi_snapshot":   rsi_snapshot,
        }

    def test_boost_applied_when_oversold(self):
        """Wire-in: ETH RSI 27.5 + BTC RSI 40.0 → size_multiplier=1.3."""
        stats = self._base_stats({
            "ETH/USD": {"today": 27.5},
            "BTC/USD": {"today": 40.0},
        })
        state = {"strategies": {"crypto-momentum": {"size_multiplier": 1.0, "enabled": True}}}
        new_state, rationale = adapt(state, stats)
        cm = new_state["strategies"]["crypto-momentum"]
        self.assertAlmostEqual(cm["size_multiplier"], 1.3)
        # Rationale should mention the boost
        self.assertTrue(
            any("oversold" in r.lower() or "27.5" in r for r in rationale),
            f"Expected oversold mention in rationale: {rationale}",
        )

    def test_no_boost_when_eth_above_threshold(self):
        """ETH RSI 35 → no boost, multiplier stays default."""
        stats = self._base_stats({
            "ETH/USD": {"today": 35.0},
            "BTC/USD": {"today": 40.0},
        })
        state = {"strategies": {"crypto-momentum": {"size_multiplier": 1.0, "enabled": True}}}
        new_state, _ = adapt(state, stats)
        cm = new_state["strategies"]["crypto-momentum"]
        self.assertAlmostEqual(cm["size_multiplier"], 1.0)

    def test_no_boost_when_disabled(self):
        """Disabled crypto-momentum gets no boost even if RSI qualifies."""
        stats = self._base_stats({
            "ETH/USD": {"today": 25.0},
            "BTC/USD": {"today": 40.0},
        })
        # consec losses = 0 but enabled=False
        state = {"strategies": {"crypto-momentum": {
            "size_multiplier": 1.0,
            "enabled": False,
            "paused_until": "2026-06-01",
        }}}
        new_state, _ = adapt(state, stats)
        cm = new_state["strategies"]["crypto-momentum"]
        # Still 1.0 because boost only applies when enabled
        self.assertAlmostEqual(cm["size_multiplier"], 1.0)

    def test_boost_doesnt_overwrite_higher_multiplier(self):
        """If current multiplier already ≥1.3 (e.g. WR-warm-up), no downgrade."""
        stats = self._base_stats({
            "ETH/USD": {"today": 25.0},
            "BTC/USD": {"today": 40.0},
        })
        # Start with size_multiplier 1.5
        state = {"strategies": {"crypto-momentum": {"size_multiplier": 1.5, "enabled": True}}}
        new_state, _ = adapt(state, stats)
        cm = new_state["strategies"]["crypto-momentum"]
        # Should stay 1.5 (heuristic only boosts UP to 1.3, never down)
        self.assertGreaterEqual(cm["size_multiplier"], 1.3)


# ─── Lane2 auto-added test for: Deep oversold crypto amplifier: ETH ≤ 25 → boost crypto-momentum to 1.5x (vs 1.3x at ≤ 30) ─────
# Auto-injected by lane2_pr to expose new symbols to the test:
from adapter import heuristic_crypto_deep_oversold_boost  # noqa: E402,F401

class TestCryptoDeepOversoldBoost(unittest.TestCase):
    def test_fires_at_eth_20_btc_30(self):
        stats = {"rsi_snapshot": {"ETH/USD": {"today": 20.7}, "BTC/USD": {"today": 30.5}}}
        fired, mult, reason = heuristic_crypto_deep_oversold_boost(stats)
        self.assertTrue(fired)
        self.assertEqual(mult, 1.5)
        self.assertIn("deep capitulation", reason)
    def test_no_fire_at_eth_27(self):
        stats = {"rsi_snapshot": {"ETH/USD": {"today": 27.0}, "BTC/USD": {"today": 40.0}}}
        fired, mult, _ = heuristic_crypto_deep_oversold_boost(stats)
        self.assertFalse(fired)
        self.assertEqual(mult, 1.0)
    def test_no_fire_btc_over_45(self):
        stats = {"rsi_snapshot": {"ETH/USD": {"today": 22.0}, "BTC/USD": {"today": 46.0}}}
        fired, _, _ = heuristic_crypto_deep_oversold_boost(stats)
        self.assertFalse(fired)
    def test_empty_rsi_snapshot_safe(self):
        fired, mult, _ = heuristic_crypto_deep_oversold_boost({})
        self.assertFalse(fired)
        self.assertEqual(mult, 1.0)


# ─── PR #9 wire-in integration tests (2026-05-23) ─────────────────────────
# Verifies that heuristic_crypto_deep_oversold_boost is actually applied
# in adapt() loop AFTER the PR #8 base boost, overriding upward.


class TestCryptoDeepOversoldBoostWiredIntoAdapt(unittest.TestCase):
    def _base_stats(self, eth_rsi, btc_rsi):
        return {
            "as_of": "2026-05-23",
            "equity": 95000.0,
            "starting_equity": 95000.0,
            "by_strategy": {
                "crypto-momentum": {
                    "trades_7d": 0, "trades_lifetime": 0,
                    "win_rate_7d": 0.0, "win_rate_lifetime": 0.0,
                    "pnl_usd_7d": 0.0, "pnl_usd_lifetime": 0.0,
                    "consecutive_losses": 0,
                },
            },
            "by_asset_class": {}, "by_source": {},
            "rsi_snapshot": {
                "ETH/USD": {"today": eth_rsi},
                "BTC/USD": {"today": btc_rsi},
            },
        }

    def test_deep_oversold_fires_15x(self):
        """ETH 20.7 + BTC 30.5 (today's actual) → size_multiplier=1.5."""
        stats = self._base_stats(eth_rsi=20.7, btc_rsi=30.5)
        state = {"strategies": {"crypto-momentum": {"size_multiplier": 1.0, "enabled": True}}}
        new_state, rationale = adapt(state, stats)
        cm = new_state["strategies"]["crypto-momentum"]
        self.assertAlmostEqual(cm["size_multiplier"], 1.5,
                                msg="PR #9: ETH ≤25 should boost to 1.5x")
        # Rationale should mention deep capitulation
        self.assertTrue(any("capitulation" in r.lower() or "1.50" in r for r in rationale),
                         f"Expected deep capitulation in rationale: {rationale}")

    def test_middle_oversold_fires_13x_only(self):
        """ETH 28 (NOT ≤25) → only PR #8 base boost 1.3x fires, not 1.5x."""
        stats = self._base_stats(eth_rsi=28.0, btc_rsi=40.0)
        state = {"strategies": {"crypto-momentum": {"size_multiplier": 1.0, "enabled": True}}}
        new_state, _ = adapt(state, stats)
        cm = new_state["strategies"]["crypto-momentum"]
        # PR #8 fires (ETH ≤30), PR #9 doesn't (ETH > 25) → 1.3x not 1.5x
        self.assertAlmostEqual(cm["size_multiplier"], 1.3)

    def test_neither_oversold_fires(self):
        """ETH 35 → neither PR #8 nor PR #9, default 1.0x."""
        stats = self._base_stats(eth_rsi=35.0, btc_rsi=50.0)
        state = {"strategies": {"crypto-momentum": {"size_multiplier": 1.0, "enabled": True}}}
        new_state, _ = adapt(state, stats)
        cm = new_state["strategies"]["crypto-momentum"]
        self.assertAlmostEqual(cm["size_multiplier"], 1.0)

    def test_deep_doesnt_downgrade(self):
        """If existing multiplier already ≥1.5 (e.g. WR-warm), no downgrade."""
        stats = self._base_stats(eth_rsi=20.0, btc_rsi=30.0)
        state = {"strategies": {"crypto-momentum": {"size_multiplier": 1.8, "enabled": True}}}
        new_state, _ = adapt(state, stats)
        cm = new_state["strategies"]["crypto-momentum"]
        self.assertGreaterEqual(cm["size_multiplier"], 1.5)


# ─── Lane2 auto-added test for: Set options_side_bias from SPY RSI when trade sample is thin ─────
# Auto-injected by lane2_pr to expose new symbols to the test:
from adapter import heuristic_options_bias_from_spy_rsi  # noqa: E402,F401

class TestOptionsBiasFromSpyRsi(unittest.TestCase):
    def test_overbought_returns_short(self):
        stats = {"rsi_snapshot": {"SPY": {"today": 74}}}
        bias, reason = heuristic_options_bias_from_spy_rsi(stats)
        self.assertEqual(bias, "short")
        self.assertIn("74", reason)

    def test_oversold_returns_long(self):
        stats = {"rsi_snapshot": {"SPY": {"today": 30}}}
        bias, reason = heuristic_options_bias_from_spy_rsi(stats)
        self.assertEqual(bias, "long")

    def test_neutral_returns_none(self):
        stats = {"rsi_snapshot": {"SPY": {"today": 55}}}
        bias, reason = heuristic_options_bias_from_spy_rsi(stats)
        self.assertIsNone(bias)

    def test_missing_rsi_data_returns_none(self):
        bias, reason = heuristic_options_bias_from_spy_rsi({})
        self.assertIsNone(bias)
        self.assertIn("no SPY RSI", reason)

    def test_boundary_exactly_72_returns_short(self):
        stats = {"rsi_snapshot": {"SPY": {"today": 72}}}
        bias, _ = heuristic_options_bias_from_spy_rsi(stats)
        self.assertEqual(bias, "short")

    def test_boundary_exactly_35_returns_long(self):
        stats = {"rsi_snapshot": {"SPY": {"today": 35}}}
        bias, _ = heuristic_options_bias_from_spy_rsi(stats)
        self.assertEqual(bias, "long")


class TestOptionsBiasMacroFallbackWiredIntoAdapt(unittest.TestCase):
    """PR #10 wire-in: macro fallback fires after _reset_options_bias_if_no_data
    clears the bias, when SPY RSI is decisive (≥72 or ≤35)."""

    def _base_state(self, current_bias):
        return {
            "strategies": {
                "options-momentum": {
                    "size_multiplier": 1.0, "enabled": True,
                    "trades_7d": 0, "trades_lifetime": 1,  # thin sample triggers reset
                    "win_rate_7d": 0.0, "pnl_7d_usd": 0.0,
                    "consec_losses": 0,
                },
            },
            "asset_classes": {}, "sources": {}, "next_actions": [],
            "global_overrides": {"options_side_bias": current_bias},
            "cumulative": {"total_trades": 0, "total_pnl_usd": 0.0, "starting_equity": 100000.0},
        }

    def test_macro_fallback_applies_short_when_spy_overbought(self):
        state = self._base_state(current_bias="long")  # stale long bias to be reset
        stats = {
            "as_of": "2026-05-27",
            "by_strategy": {"options-momentum": {"trades_7d": 0, "win_rate_7d": 0}},
            "rsi_snapshot": {"SPY": {"today": 73.5}},
        }
        new_state, rationale = adapt(state, stats)
        self.assertEqual(new_state["global_overrides"]["options_side_bias"], "short")
        self.assertTrue(any("macro fallback" in r and "short" in r for r in rationale))

    def test_macro_fallback_applies_long_when_spy_oversold(self):
        state = self._base_state(current_bias="short")
        stats = {
            "as_of": "2026-05-27",
            "by_strategy": {"options-momentum": {"trades_7d": 0, "win_rate_7d": 0}},
            "rsi_snapshot": {"SPY": {"today": 30.0}},
        }
        new_state, _ = adapt(state, stats)
        self.assertEqual(new_state["global_overrides"]["options_side_bias"], "long")

    def test_macro_fallback_keeps_null_in_neutral_zone(self):
        state = self._base_state(current_bias="short")
        stats = {
            "as_of": "2026-05-27",
            "by_strategy": {"options-momentum": {"trades_7d": 0, "win_rate_7d": 0}},
            "rsi_snapshot": {"SPY": {"today": 55.0}},
        }
        new_state, _ = adapt(state, stats)
        # reset cleared to None, macro neutral → stays None
        self.assertIsNone(new_state["global_overrides"]["options_side_bias"])

    def test_macro_fallback_does_not_override_when_trade_data_sufficient(self):
        # trades_7d=10 → _reset_options_bias_if_no_data returns False → macro skipped
        state = self._base_state(current_bias="long")
        state["strategies"]["options-momentum"]["trades_7d"] = 10
        stats = {
            "as_of": "2026-05-27",
            "by_strategy": {"options-momentum": {"trades_7d": 10, "win_rate_7d": 0.6}},
            "rsi_snapshot": {"SPY": {"today": 73.5}},  # would suggest short
        }
        new_state, _ = adapt(state, stats)
        # trade-based bias preserved (long), macro fallback not triggered
        self.assertEqual(new_state["global_overrides"]["options_side_bias"], "long")
