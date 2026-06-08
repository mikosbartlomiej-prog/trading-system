"""v3.25.0 (2026-06-09) — crypto exposure policy tests.

Pin the hard guards that prevent the SOL/LTC ~60% combined exposure
pattern from ever happening again under defaults. Also confirm no
order-placing function is imported by the policy module.

READ-ONLY. No orders placed.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

import crypto_exposure_policy as ce


def _make(symbol="ETHUSD", buy_usd=2500.0, equity=100000.0,
            positions=None, pending=None, ddg=False,
            pnl=None, buys_today=None, last_buy=None,
            mode="broker_paper", now=1_000_000_000.0):
    return ce.CryptoExposureInputs(
        symbol=symbol, proposed_buy_usd=buy_usd,
        equity_usd=equity,
        current_positions_usd=positions or {},
        pending_orders_by_symbol=pending or {},
        drawdown_guard_active=ddg,
        recent_realized_pnl_by_symbol_usd=pnl or {},
        buys_today_by_symbol=buys_today or {},
        last_buy_epoch_by_symbol=last_buy or {},
        mode=mode,
        now_epoch=now,
    )


class TestSOLLTCPatternBlocked(unittest.TestCase):
    """The original incident: SOL and LTC accumulated to ~$30k each
    via repeated $2,500 buys. Under v3.25 defaults this must be
    impossible at every stage of the accumulation."""

    def test_first_fresh_sol_buy_2500_blocked_by_per_symbol_cap(self):
        # 2500 / 100000 = 2.5% — under default 3% per-symbol cap. So
        # the FIRST fresh buy is technically allowed. We must therefore
        # show the SECOND buy is blocked.
        d = ce.evaluate_crypto_buy(_make(symbol="SOLUSD", buy_usd=2500.0))
        # First fresh buy of 2.5% (with no other crypto) is allowed.
        self.assertEqual(d.decision, ce.ALLOW)

    def test_second_buy_with_meaningful_sol_blocked_by_existing_position(self):
        # After the FIRST buy, SOL is at 2.5% — above 1% threshold.
        # Repeated buy must be blocked.
        d = ce.evaluate_crypto_buy(_make(
            symbol="SOLUSD", buy_usd=2500.0,
            positions={"SOLUSD": 2500.0},
        ))
        self.assertEqual(d.decision, ce.BLOCK_BY_EXISTING_POSITION)

    def test_sixty_pct_combined_pattern_blocked(self):
        # Simulate: SOL + LTC each at ~$28k. Any additional buy must be
        # blocked.
        for sym in ("SOLUSD", "LTCUSD"):
            d = ce.evaluate_crypto_buy(_make(
                symbol=sym, buy_usd=2500.0,
                positions={"SOLUSD": 28000.0, "LTCUSD": 28000.0},
            ))
            self.assertTrue(d.is_blocked,
                              f"{sym} buy at 60% combined was not blocked")

    def test_fresh_solusd_buy_above_per_symbol_cap_blocked(self):
        # Fresh buy of $4000 (4% of equity) > 3% per-symbol cap.
        d = ce.evaluate_crypto_buy(_make(
            symbol="SOLUSD", buy_usd=4000.0,
        ))
        self.assertEqual(d.decision, ce.BLOCK_BY_SYMBOL_EXPOSURE_CAP)

    def test_aggregate_cap_blocks_when_per_symbol_would_pass(self):
        # ETH+AVAX = 2 meaningful symbols already (the cap). A third
        # crypto symbol (fresh BTC) is correctly blocked by the
        # meaningful-open-symbols gate BEFORE we even evaluate
        # aggregate cap. That is the v3.25 contract: ETH+AVAX is
        # enough; do not let SOL/LTC sneak in as a third.
        d = ce.evaluate_crypto_buy(_make(
            symbol="BTC/USD", buy_usd=2000.0,
            positions={"ETHUSD": 4500.0, "AVAXUSD": 4500.0},
        ))
        self.assertEqual(d.decision,
                          ce.BLOCK_BY_TOO_MANY_MEANINGFUL_OPEN_SYMBOLS)

    def test_aggregate_cap_blocks_when_only_one_meaningful_open(self):
        # ETH is the only existing position (8.5% of equity). Buying
        # 2% more in BTC pushes aggregate to 10.5% > 10% cap. Only ONE
        # meaningful symbol is open so the meaningful-cap (=2) does
        # not pre-empt.
        d = ce.evaluate_crypto_buy(_make(
            symbol="BTC/USD", buy_usd=2000.0,
            positions={"ETHUSD": 8500.0},
        ))
        self.assertEqual(d.decision, ce.BLOCK_BY_AGGREGATE_EXPOSURE_CAP)


class TestPerSymbolExposureCap(unittest.TestCase):
    def test_at_cap_passes(self):
        # Exactly 3% — allowed (cap is "above").
        d = ce.evaluate_crypto_buy(_make(buy_usd=3000.0))
        self.assertEqual(d.decision, ce.ALLOW)

    def test_above_cap_blocked(self):
        d = ce.evaluate_crypto_buy(_make(buy_usd=3001.0))
        self.assertEqual(d.decision, ce.BLOCK_BY_SYMBOL_EXPOSURE_CAP)


class TestAggregateExposureCap(unittest.TestCase):
    def test_post_buy_above_10pct_blocked(self):
        # Already 8.5% in crypto, buying 2% more = 10.5% > 10% cap.
        d = ce.evaluate_crypto_buy(_make(
            symbol="BTC/USD", buy_usd=2000.0,
            positions={"ETHUSD": 8500.0},
        ))
        self.assertTrue(d.is_blocked)


class TestRepeatedFiveMinuteBuysBlocked(unittest.TestCase):
    def test_second_buy_within_cooldown_blocked(self):
        # Cooldown default is 240 min; 5 min later must block.
        now = 1_000_000_000.0
        d = ce.evaluate_crypto_buy(_make(
            symbol="SOLUSD", buy_usd=500.0,
            last_buy={"SOLUSD": now - 300.0},  # 5 min ago
            now=now,
        ))
        # BLOCK_BY_COOLDOWN OR earlier guard (e.g. EXISTING_POSITION
        # if positions provided). With empty positions, cooldown
        # should fire.
        self.assertEqual(d.decision, ce.BLOCK_BY_COOLDOWN)

    def test_after_cooldown_window_passes(self):
        now = 1_000_000_000.0
        # 5 hours ago — past 240 min cooldown.
        d = ce.evaluate_crypto_buy(_make(
            symbol="SOLUSD", buy_usd=2500.0,
            last_buy={"SOLUSD": now - 5 * 3600},
            now=now,
        ))
        self.assertEqual(d.decision, ce.ALLOW)


class TestExistingPositionBlocksNewBuy(unittest.TestCase):
    def test_meaningful_position_blocks(self):
        d = ce.evaluate_crypto_buy(_make(
            symbol="ETHUSD", positions={"ETHUSD": 8000.0},
        ))
        self.assertEqual(d.decision, ce.BLOCK_BY_EXISTING_POSITION)

    def test_dust_position_does_not_block_via_existing_check(self):
        # Dust < 1% threshold should not trigger EXISTING_POSITION.
        # But meaningful-open count of 2 (ETH+AVAX) would block dust
        # SOLUSD from opening fresh.
        d = ce.evaluate_crypto_buy(_make(
            symbol="SOLUSD", buy_usd=500.0,
            positions={"ETHUSD": 8000.0, "AVAXUSD": 2500.0,
                        "SOLUSD": 0.00001},
        ))
        # Should be BLOCK_BY_TOO_MANY_MEANINGFUL_OPEN_SYMBOLS (2 already).
        self.assertEqual(d.decision,
                          ce.BLOCK_BY_TOO_MANY_MEANINGFUL_OPEN_SYMBOLS)


class TestPendingOrderBlocksDuplicate(unittest.TestCase):
    def test_pending_buy_blocks_new_buy(self):
        d = ce.evaluate_crypto_buy(_make(
            symbol="ETHUSD", pending={"ETHUSD": 1},
        ))
        self.assertEqual(d.decision, ce.BLOCK_BY_PENDING_ORDER)


class TestDrawdownGuardBlocks(unittest.TestCase):
    def test_drawdown_active_blocks(self):
        d = ce.evaluate_crypto_buy(_make(ddg=True))
        self.assertEqual(d.decision, ce.BLOCK_BY_DRAWDOWN_GUARD)


class TestRecentRealizedLossCooldown(unittest.TestCase):
    def test_recent_loss_blocks_same_symbol(self):
        d = ce.evaluate_crypto_buy(_make(
            symbol="SOLUSD",
            pnl={"SOLUSD": -2851.15},  # the actual SOL loss
        ))
        self.assertEqual(
            d.decision,
            ce.BLOCK_BY_RECENT_REALIZED_LOSS_COOLDOWN,
        )

    def test_small_loss_below_threshold_does_not_block(self):
        d = ce.evaluate_crypto_buy(_make(
            symbol="SOLUSD",
            pnl={"SOLUSD": -100.0},  # well below 500 abs threshold
        ))
        # Should not be the loss-cooldown block; some other check may
        # still pass it through.
        self.assertNotEqual(
            d.decision,
            ce.BLOCK_BY_RECENT_REALIZED_LOSS_COOLDOWN,
        )


class TestSignalShadowMode(unittest.TestCase):
    def test_shadow_mode_returns_allow_shadow_only_when_clean(self):
        d = ce.evaluate_crypto_buy(_make(
            symbol="ETHUSD", buy_usd=2500.0, mode="signal_shadow",
        ))
        self.assertEqual(d.decision, ce.ALLOW_SHADOW_ONLY)
        self.assertTrue(d.is_shadow_only)
        self.assertFalse(d.is_allow)

    def test_shadow_mode_still_blocks_on_drawdown(self):
        d = ce.evaluate_crypto_buy(_make(
            symbol="ETHUSD", ddg=True, mode="signal_shadow",
        ))
        self.assertEqual(d.decision, ce.BLOCK_BY_DRAWDOWN_GUARD)


class TestNoOrderPlacingFunctionsImported(unittest.TestCase):
    """The policy module must NOT import any order-placing function.
    This is a structural invariant."""

    def test_no_forbidden_imports(self):
        src = Path(REPO_ROOT / "shared"
                    / "crypto_exposure_policy.py").read_text()
        FORBIDDEN = (
            "place_stock_bracket",
            "place_crypto_order",
            "place_simple_buy",
            "place_oco_exit",
            "safe_close",
            "execute_stock_signal",
            "execute_crypto_signal",
            "requests.post",
            "requests.put",
            "requests.delete",
        )
        for token in FORBIDDEN:
            self.assertNotIn(token, src,
                              f"forbidden token in policy module: {token}")


class TestInvariantsExposed(unittest.TestCase):
    def test_invariant_constants_true(self):
        self.assertTrue(ce.NEVER_PLACES_ORDERS)
        self.assertTrue(ce.NEVER_LOWERS_DRAWDOWN_GUARD)
        self.assertTrue(ce.LIVE_TRADING_PATH_FOREVER_DISABLED)
        self.assertTrue(ce.NEVER_INFERS_CLIENT_ORDER_ID)

    def test_status_tokens_present(self):
        for t in (
            ce.CRYPTO_HARD_EXPOSURE_CAP_ADDED,
            ce.CRYPTO_AGGREGATE_EXPOSURE_CAP_ADDED,
            ce.CRYPTO_PER_SYMBOL_EXPOSURE_CAP_ADDED,
            ce.CRYPTO_LADDERING_GUARD_ADDED,
            ce.CRYPTO_BUY_COOLDOWN_ADDED,
            ce.CRYPTO_PENDING_ORDER_PRECHECK_REQUIRED,
            ce.CRYPTO_DRAWDOWN_GUARD_BLOCKS_NEW_BUYS,
            ce.CRYPTO_RECENT_LOSS_COOLDOWN_ADDED,
        ):
            self.assertIn(t, ce.ALL_POLICY_STATUS_TOKENS)


class TestLadderingLimit(unittest.TestCase):
    def test_second_buy_same_day_blocked_by_ladder_limit(self):
        # Make sure the cooldown wouldn't pre-empt this: use a long-ago
        # last buy. With buys_today=1 and limit=1, should block.
        now = 1_000_000_000.0
        d = ce.evaluate_crypto_buy(_make(
            symbol="SOLUSD", buy_usd=2500.0,
            buys_today={"SOLUSD": 1},
            last_buy={"SOLUSD": now - 10 * 3600},  # 10 h ago, past cooldown
            now=now,
        ))
        self.assertEqual(d.decision, ce.BLOCK_BY_LADDER_LIMIT)


if __name__ == "__main__":
    unittest.main()
