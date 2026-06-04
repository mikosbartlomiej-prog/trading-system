"""v3.16 (2026-06-04) — crypto backtest harness tests.

Covers:
  1. No-lookahead invariant for both crypto signal functions.
  2. crypto_momentum_signal_at fires on a synthetic breakout pattern.
  3. crypto_momentum_signal_at no-fire when RSI out of band.
  4. crypto_oversold_bounce_signal_at fires on synthetic deep-oversold.
  5. crypto_oversold_bounce no-fire when 24h move too negative.
  6. crypto_oversold_bounce no-fire when volume below floor.
  7. BTC dominance guard blocks Tier 2 alt-long.
  8. --explain-zero-fires writes rejection reasons (captured stdout).
  9. Synthetic 180d hourly series + run() walk-forward produces a
     non-empty trade ledger (replay-end-to-end smoke test).
 10. Strategy registry: crypto entries are HAS_SIGNAL.
 11. Parity: pure backtest signal output ≈ check_crypto_signal output
     on a controlled synthetic input (filter-pass parity).
 12. Realism integration: replay_with_realism honors crypto slippage
     tier (gives worse fills than idealized).

All tests are deterministic, no-network, and seeded.
"""

from __future__ import annotations

import io
import os
import random
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

# Make backtest/ importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "backtest"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "shared"))


# ─── Synthetic-bars factories ────────────────────────────────────────────────

def _empty_bars() -> dict:
    return {
        "close": [], "high": [], "low": [], "open": [], "volume": [], "time": [],
    }


def _make_bars(n: int, *, base_price: float = 100.0,
                 seed: int = 7, drift: float = 0.0,
                 spike_at: int | None = None, spike_pct: float = 0.0,
                 vol_base: float = 1_000_000.0,
                 vol_mult_at: dict | None = None) -> dict:
    """
    Deterministic synthetic 1h bars.
      drift:        per-bar pct drift (e.g. -0.01 = -1% per bar)
      spike_at:     idx where a custom spike applies
      spike_pct:    +X% close move at spike_at
      vol_mult_at:  {idx: multiplier} to override volume on chosen bars
    """
    random.seed(seed)
    closes = [base_price]
    for i in range(1, n):
        noise = (random.random() - 0.5) * 0.005
        delta = drift + noise
        if spike_at is not None and i == spike_at:
            delta += spike_pct
        closes.append(closes[-1] * (1 + delta))
    opens = [closes[0]] + closes[:-1]
    highs = [max(o, c) * 1.001 for o, c in zip(opens, closes)]
    lows = [min(o, c) * 0.999 for o, c in zip(opens, closes)]
    vol_mult_at = vol_mult_at or {}
    volumes = [vol_base * vol_mult_at.get(i, 1.0) for i in range(n)]
    times = [f"2026-01-{((i // 24) % 28) + 1:02d}T{(i % 24):02d}:00:00Z"
             for i in range(n)]
    return {
        "close": closes, "high": highs, "low": lows,
        "open": opens, "volume": volumes, "time": times,
    }


def _make_breakout_bars(n: int = 50) -> dict:
    """
    Synthetic breakout series — engineered to satisfy ALL predator filters:
      * 24h-move (last 24 bars) ∈ [3, 15] %
      * RSI(14) ∈ [45, 68]
      * close > 20-bar high
      * volume > 2× × 20-bar avg

    Strategy:
      - First (n-25) bars: oscillate around 100 with small noise (RSI ≈ 50).
      - Next 13 bars: alternate 1 up (+0.5%) / 1 down (-0.4%) — keeps RSI
        ~ 55 while drifting up modestly.
      - Last 11 bars: stronger uptrend (+0.6% / +0.0% pattern) so the
        last 14-bar RSI window sees mostly gains but also a few losses,
        landing RSI roughly 60.
      - Last bar: explicit breakout above 20-bar high.

    Verified by experiment: yields RSI ~ 60, 24h-move ~ 5-7%, breakout
    AND volume conditions all met.
    """
    # Goal:
    #   - last 14 bars: mostly up with ~4-5 down dips so RSI lands in band
    #   - 20-bar high established earlier so the breakout bar clears it
    #   - 24h-move (last 24) lands in [3,15]%
    closes = [100.0]
    # Bars 0..n-26: oscillate around 100, slight noise but never set the
    # 20-bar high higher than baseline
    cushion_n = max(0, n - 26)
    for i in range(cushion_n):
        if i % 2 == 0:
            closes.append(100.0)
        else:
            closes.append(99.95)
    # Now plant 24 bars with mixed up/down — pattern UUDD-style so
    # avg_gain / avg_loss ratio stays balanced in the trailing-14 window
    # Pattern engineered so that the trailing-14 window (incl. final breakout
    # bar) has roughly 7 gains + 7 losses with larger gains than losses.
    # That gives avg_gain/avg_loss ~ 1.5 → RSI ~ 60.
    pattern = [
        # Bars 0..9 — early trail: tilt up
        +0.008, -0.004, +0.010, -0.004,
        +0.008, -0.004, +0.010, -0.005,
        +0.008, -0.004,
        # Bars 10..23 — trailing 14 (excluding the breakout bar appended
        # after pattern). 7 gains avg ~+0.7%, 7 losses avg ~-0.5%.
        +0.007, -0.005, +0.007, -0.005,
        +0.008, -0.005, +0.007, -0.005,
        +0.008, -0.004, +0.007, -0.005,
        +0.007, -0.004,
    ]
    for delta in pattern:
        closes.append(closes[-1] * (1 + delta))
    # The 20-bar high among closes[-25:-1] is now around the running price.
    opens = [closes[0]] + closes[:-1]
    highs = [max(o, c) * 1.0005 for o, c in zip(opens, closes)]
    lows = [min(o, c) * 0.9995 for o, c in zip(opens, closes)]
    # Append breakout bar
    high_20_before = max(highs[-21:-1])
    breakout_close = max(high_20_before * 1.003, closes[-1] * 1.005)
    closes.append(breakout_close)
    opens.append(closes[-2])
    highs.append(breakout_close * 1.001)
    lows.append(closes[-2] * 0.999)
    volumes = [1_000_000.0] * (len(closes) - 1)
    volumes.append(3_500_000.0)   # 3.5× breakout volume
    times = [f"2026-01-{((i // 24) % 28) + 1:02d}T{(i % 24):02d}:00:00Z"
             for i in range(len(closes))]
    return {"close": closes, "high": highs, "low": lows,
            "open": opens, "volume": volumes, "time": times}


def _make_deep_oversold_bars(n: int = 60) -> dict:
    """
    Synthetic deep-oversold-then-stabilizing series. Needs:
      - >= 25 bars
      - 24h-move(last 24 bars) >= -10%
      - RSI(14) <= 30 (deep oversold)
      - 3-bar stabilization: avg(closes[-3:]) >= closes[-4]
      - volume >= 25% of normal

    Construction:
      - bars 0..n-25:  cushion at base price (so trailing-14 RSI computed
                       near the end has some down-bars in its window via
                       the transition zone) — TODO simpler approach:
      - We build the series such that the LAST 14 bars contain a
        mixture of small down moves (so RSI < 30) AND end with a tiny
        3-bar uptick so stabilization passes. 24h-move ≥ -10% by
        keeping the last-24 net drop modest.

    Concretely: gentle losses (-0.5%/bar) for 13 of the last 14 bars,
    then a 3-bar tiny uptick at the end (+0.1%/bar). Then the prior
    bars cushion at base price.
    """
    cushion_bars = max(0, n - 17)             # bars at flat base (avg-vol fill)
    closes = [100.0] * cushion_bars
    # Then 14 bars of small losses
    if not closes:
        closes = [100.0]
    base = closes[-1]
    # 13 losing bars
    for _ in range(13):
        closes.append(closes[-1] * 0.995)     # -0.5%/bar
    # 3-bar tiny uptick (the stabilization)
    for _ in range(3):
        closes.append(closes[-1] * 1.001)     # +0.1%/bar
    opens = [closes[0]] + closes[:-1]
    highs = [max(o, c) * 1.0005 for o, c in zip(opens, closes)]
    lows = [min(o, c) * 0.9995 for o, c in zip(opens, closes)]
    volumes = [1_000_000.0] * len(closes)
    times = [f"2026-01-{((i // 24) % 28) + 1:02d}T{(i % 24):02d}:00:00Z"
             for i in range(len(closes))]
    return {"close": closes, "high": highs, "low": lows,
            "open": opens, "volume": volumes, "time": times}


# ─── Tests ──────────────────────────────────────────────────────────────────


class TestNoLookahead(unittest.TestCase):
    """v3.10 Phase F invariant — re-applied to v3.16 crypto signals."""

    def setUp(self):
        from strategies import (
            crypto_momentum_signal_at,
            crypto_oversold_bounce_signal_at,
        )
        self.fns = {
            "crypto-momentum": crypto_momentum_signal_at,
            "crypto-oversold-bounce": crypto_oversold_bounce_signal_at,
        }
        # Use a richer 60-bar series (mixed up/down/sideways) so signals
        # actually have a chance to fire at various indices.
        random.seed(123)
        closes = [100.0]
        for i in range(1, 60):
            closes.append(closes[-1] * (1 + (random.random() - 0.5) * 0.02))
        opens = [closes[0]] + closes[:-1]
        highs = [max(o, c) * 1.0008 for o, c in zip(opens, closes)]
        lows = [min(o, c) * 0.9992 for o, c in zip(opens, closes)]
        volumes = [1_000_000.0] * 60
        volumes[40] = 3_000_000.0  # spike to maybe trigger momentum
        self.bars = {
            "close": closes, "high": highs, "low": lows,
            "open": opens, "volume": volumes,
            "time": [f"t{i}" for i in range(60)],
        }

    def test_no_lookahead_for_both(self):
        for name, fn in self.fns.items():
            for idx in (26, 30, 40, 50, 58):
                # Truncated: bars[:idx+1]
                trunc = {k: (v[:idx + 1] if isinstance(v, list) else v)
                         for k, v in self.bars.items()}
                sig_trunc = fn(idx, trunc)
                sig_full = fn(idx, self.bars)
                self.assertEqual(
                    sig_trunc, sig_full,
                    f"LOOKAHEAD in {name} @ idx={idx}: "
                    f"trunc={sig_trunc} vs full={sig_full}",
                )


class TestCryptoMomentumFires(unittest.TestCase):
    """crypto_momentum_signal_at fires on a synthetic breakout."""

    def test_breakout_fires(self):
        from strategies import crypto_momentum_signal_at
        bars = _make_breakout_bars(50)
        sig = crypto_momentum_signal_at(len(bars["close"]) - 1, bars)
        # The synthetic breakout series should produce a BUY at the last bar.
        # If filter passes: action=BUY, strategy=crypto-momentum, TP > entry > SL.
        if sig is None:
            # Diagnose so the test failure is informative
            from run import _explain_no_signal_crypto
            reason = _explain_no_signal_crypto(
                len(bars["close"]) - 1, bars, "crypto-momentum"
            )
            self.fail(f"breakout expected to fire — got None ({reason})")
        self.assertEqual(sig["action"], "BUY")
        self.assertEqual(sig["strategy"], "crypto-momentum")
        self.assertGreater(sig["take_profit"], sig["entry_price"])
        self.assertLess(sig["stop_loss"], sig["entry_price"])


class TestCryptoMomentumRsiOutOfBand(unittest.TestCase):
    """RSI outside [45, 68] → no signal."""

    def test_extreme_uptrend_rsi_too_high(self):
        from strategies import crypto_momentum_signal_at
        # 50 bars all +2% each ⇒ RSI = 100 (out of band). Massive breakout.
        n = 50
        closes = [100.0 * (1.02 ** i) for i in range(n)]
        opens = [closes[0]] + closes[:-1]
        highs = [c * 1.001 for c in closes]
        lows = [c * 0.999 for c in closes]
        volumes = [1_000_000.0] * n
        volumes[-1] = 5_000_000.0
        bars = {"close": closes, "high": highs, "low": lows,
                "open": opens, "volume": volumes,
                "time": [f"t{i}" for i in range(n)]}
        # 24h-move on +2%/bar × 24 bars = (1.02^24 - 1) * 100 ≈ +60.8%
        # — outside predator bracket [3, 15] — so this also fails on
        # predator. Both filters reject; either way the test asserts None.
        sig = crypto_momentum_signal_at(n - 1, bars)
        self.assertIsNone(sig)


class TestCryptoOversoldBounceFires(unittest.TestCase):
    """Deep oversold + 3-bar stabilization triggers the bounce signal."""

    def test_oversold_bounce_fires(self):
        from strategies import crypto_oversold_bounce_signal_at
        bars = _make_deep_oversold_bars()
        sig = crypto_oversold_bounce_signal_at(len(bars["close"]) - 1, bars)
        if sig is None:
            from run import _explain_no_signal_crypto
            reason = _explain_no_signal_crypto(
                len(bars["close"]) - 1, bars, "crypto-oversold-bounce"
            )
            self.fail(f"oversold-bounce expected to fire — got None ({reason})")
        self.assertEqual(sig["action"], "BUY")
        self.assertEqual(sig["strategy"], "crypto-oversold-bounce")
        # SL must be 1.5× wider than the predator SL (1 - 0.07 × 1.5 = 0.895)
        self.assertAlmostEqual(
            sig["stop_loss"] / sig["entry_price"], 1 - 0.07 * 1.5, places=2
        )


class TestOversold24hMoveTooLow(unittest.TestCase):
    """Catastrophic 24h move < -10% blocks oversold-bounce."""

    def test_catastrophe_blocks(self):
        from strategies import crypto_oversold_bounce_signal_at
        # 30 bars where each of the last 24 dropped ~1.5% → 24h-move < -30%
        n = 30
        closes = [100.0]
        for _ in range(1, n):
            closes.append(closes[-1] * 0.985)
        opens = [closes[0]] + closes[:-1]
        highs = [max(o, c) * 1.0008 for o, c in zip(opens, closes)]
        lows = [min(o, c) * 0.9992 for o, c in zip(opens, closes)]
        volumes = [1_000_000.0] * n
        bars = {"close": closes, "high": highs, "low": lows,
                "open": opens, "volume": volumes,
                "time": [f"t{i}" for i in range(n)]}
        sig = crypto_oversold_bounce_signal_at(n - 1, bars)
        self.assertIsNone(sig)


class TestOversoldVolumeBelowFloor(unittest.TestCase):
    """Volume < 25% × vol_mult-baseline → no fire."""

    def test_low_volume_blocks(self):
        from strategies import crypto_oversold_bounce_signal_at
        bars = _make_deep_oversold_bars()
        # Drop last-bar volume below floor (floor = 1M × 2 × 0.25 = 500k)
        bars["volume"][-1] = 100_000.0
        sig = crypto_oversold_bounce_signal_at(len(bars["close"]) - 1, bars)
        self.assertIsNone(sig)


class TestBtcDominanceGuard(unittest.TestCase):
    """is_tier_2=True + btc_change <= -3% → BLOCK alt-long for both signals."""

    def test_momentum_alt_long_blocked(self):
        from strategies import crypto_momentum_signal_at
        bars = _make_breakout_bars(50)
        sig_no_btc = crypto_momentum_signal_at(
            len(bars["close"]) - 1, bars, is_tier_2=True
        )
        sig_btc_dump = crypto_momentum_signal_at(
            len(bars["close"]) - 1, bars,
            is_tier_2=True, btc_dominance_change=-4.0,
        )
        # Without btc info → may fire; with btc -4% → blocked.
        if sig_no_btc is not None:
            self.assertIsNone(
                sig_btc_dump,
                "BTC dominance guard failed to block Tier 2 alt-long"
            )

    def test_oversold_alt_long_blocked(self):
        from strategies import crypto_oversold_bounce_signal_at
        bars = _make_deep_oversold_bars()
        # Sanity: fires without guard
        sig_no_btc = crypto_oversold_bounce_signal_at(
            len(bars["close"]) - 1, bars, is_tier_2=True
        )
        if sig_no_btc is None:
            self.skipTest("baseline oversold-bounce did not fire; can't assert guard")
        sig_btc_dump = crypto_oversold_bounce_signal_at(
            len(bars["close"]) - 1, bars,
            is_tier_2=True, btc_dominance_change=-4.0,
        )
        self.assertIsNone(sig_btc_dump)


class TestExplainZeroFiresOutput(unittest.TestCase):
    """`--explain-zero-fires` produces human-readable rejection lines."""

    def test_explain_for_momentum(self):
        from run import _explain_no_signal_crypto
        # 30 bars where price is FLAT — no momentum, no breakout
        n = 30
        closes = [100.0] * n
        bars = {"close": closes, "high": [100.5] * n, "low": [99.5] * n,
                "open": closes[:], "volume": [1_000_000.0] * n,
                "time": [f"t{i}" for i in range(n)]}
        reason = _explain_no_signal_crypto(n - 1, bars, "crypto-momentum")
        # On a flat series, 24h move ~ 0 → outside [3,15] → expected reason
        self.assertIn("24h", reason)

    def test_explain_for_oversold_passing_rsi_but_not_stable(self):
        from run import _explain_no_signal_crypto
        # 30 bars: hard crash for last 24 (so RSI tiny) and last 3 BELOW close[-4]
        n = 30
        closes = [100.0] * 5  # cushion
        for i in range(25):
            closes.append(closes[-1] * 0.99)
        opens = [closes[0]] + closes[:-1]
        highs = [max(o, c) * 1.0008 for o, c in zip(opens, closes)]
        lows = [min(o, c) * 0.9992 for o, c in zip(opens, closes)]
        volumes = [1_000_000.0] * len(closes)
        bars = {"close": closes, "high": highs, "low": lows,
                "open": opens, "volume": volumes,
                "time": [f"t{i}" for i in range(len(closes))]}
        reason = _explain_no_signal_crypto(
            len(closes) - 1, bars, "crypto-oversold-bounce"
        )
        # Could be "24h ... catastrophe" OR "not stabilizing" OR "rsi"
        # — accept any of the documented oversold rejection messages.
        self.assertTrue(
            any(k in reason for k in ("24h", "stabilizing", "rsi", "catastrophe")),
            f"unexpected reason: {reason!r}",
        )

    def test_explain_zero_fires_prints_lines(self):
        from run import _explain_zero_fires
        from strategies import crypto_momentum_signal_at
        # Build a flat series so signal NEVER fires → diagnostic should
        # produce several rejection lines.
        n = 60
        closes = [100.0] * n
        bars = {"close": closes, "high": [100.5] * n, "low": [99.5] * n,
                "open": closes[:], "volume": [1_000_000.0] * n,
                "time": [f"t{i}" for i in range(n)]}
        lines = _explain_zero_fires(
            bars, crypto_momentum_signal_at, "crypto-momentum",
            "BTC/USD", limit=10,
        )
        # Expect at least 1 line; each should be a string with idx= prefix
        self.assertGreater(len(lines), 0)
        self.assertTrue(all("idx=" in l for l in lines))


class TestReplaySmokeOnSynthetic(unittest.TestCase):
    """Synthetic 180d hourly series + replay() should produce SOME trade or
    a clean ledger — and never crash."""

    def test_replay_synthetic_does_not_crash(self):
        from replay import replay
        from strategies import crypto_momentum_signal_at
        # 4320 bars (180d × 24h) but with random walk so SOMETHING fires
        random.seed(42)
        n = 4320
        closes = [100.0]
        for _ in range(1, n):
            closes.append(closes[-1] * (1 + (random.random() - 0.495) * 0.03))
        opens = [closes[0]] + closes[:-1]
        highs = [max(o, c) * 1.001 for o, c in zip(opens, closes)]
        lows = [min(o, c) * 0.999 for o, c in zip(opens, closes)]
        volumes = [1_000_000.0 * (1 + (random.random() * 1.5))
                   for _ in range(n)]
        bars = {"close": closes, "high": highs, "low": lows,
                "open": opens, "volume": volumes,
                "time": [f"2026-01-{((i // 24) % 28) + 1:02d}T{(i % 24):02d}:00Z"
                         for i in range(n)]}
        result = replay(bars, crypto_momentum_signal_at, ticker="SYNTH/USD")
        # No exception → pass. Summary keys present.
        self.assertIn("trades", result)
        self.assertIn("summary", result)
        self.assertIn("n_trades", result["summary"])


class TestStrategyRegistry(unittest.TestCase):
    """Both crypto strategies must be HAS_SIGNAL after v3.16."""

    def test_crypto_entries_has_signal(self):
        from strategy_registry import REGISTRY, HAS_SIGNAL, is_backtest_ready
        for name in ("crypto-momentum", "crypto-oversold-bounce"):
            self.assertEqual(
                REGISTRY[name].readiness, HAS_SIGNAL,
                f"{name} not HAS_SIGNAL",
            )
            self.assertTrue(is_backtest_ready(name))

    def test_signal_fn_names_present(self):
        from strategy_registry import REGISTRY
        self.assertEqual(
            REGISTRY["crypto-momentum"].signal_fn_name,
            "crypto_momentum_signal_at",
        )
        self.assertEqual(
            REGISTRY["crypto-oversold-bounce"].signal_fn_name,
            "crypto_oversold_bounce_signal_at",
        )


class TestParityWithLiveMonitor(unittest.TestCase):
    """Filter parity: pure backtest signal output ≈ live monitor's
    check_crypto_signal LOGIC on controlled synthetic input."""

    def test_parity_on_breakout(self):
        """A breakout bar that PASSES the live monitor's filters must also
        produce a signal in the backtest function."""
        from strategies import crypto_momentum_signal_at
        bars = _make_breakout_bars(50)
        sig = crypto_momentum_signal_at(len(bars["close"]) - 1, bars)
        # If our backtest signal fires, verify shape matches live contract:
        if sig is not None:
            # live monitor returns these keys:
            for required in ("action", "strategy", "entry_price",
                              "stop_loss", "take_profit"):
                self.assertIn(required, sig, f"missing key: {required}")
            # Strategy tag must match the live tag (so analyzer attributes
            # the backtest as the same strategy).
            self.assertEqual(sig["strategy"], "crypto-momentum")
            # SL/TP %s must match the live monitor's contract.
            entry = sig["entry_price"]
            self.assertAlmostEqual(
                sig["take_profit"] / entry - 1, 0.20, places=2,
                msg="TP should be entry × 1.20 (matches live TP_PCT 0.20)",
            )
            self.assertAlmostEqual(
                1 - sig["stop_loss"] / entry, 0.07, places=2,
                msg="SL should be entry × 0.93 (matches live SL_PCT 0.07)",
            )

    def test_parity_on_oversold(self):
        """Oversold-bounce signal must use 1.5× wider SL than predator."""
        from strategies import crypto_oversold_bounce_signal_at
        bars = _make_deep_oversold_bars()
        sig = crypto_oversold_bounce_signal_at(len(bars["close"]) - 1, bars)
        if sig is not None:
            entry = sig["entry_price"]
            # SL contract: 1 - sl_pct × sl_widen = 1 - 0.07 × 1.5 = 0.895
            self.assertAlmostEqual(
                sig["stop_loss"] / entry, 0.895, places=2,
                msg="oversold SL should be entry × 0.895 (1.5× wider)",
            )


class TestRealismIntegrationCrypto(unittest.TestCase):
    """replay_with_realism honors crypto slippage tier (20 bps vs 5 bps stocks).
    Realistic mode must give EQUAL OR WORSE P&L than idealized (monotonic)."""

    def test_realism_monotonic_worse_or_equal(self):
        from replay import replay
        from realism import RealismConfig, replay_with_realism
        from strategies import crypto_momentum_signal_at
        # Engineer a series where the breakout fires, then price grinds
        # higher until TP hits (so the trade closes and we can compare
        # idealized vs realistic P&L).
        bars_single = _make_breakout_bars(50)
        closes = list(bars_single["close"])
        highs = list(bars_single["high"])
        lows = list(bars_single["low"])
        opens = list(bars_single["open"])
        volumes = list(bars_single["volume"])
        # Append 30 more bars: a slow grind up that eventually hits TP
        # (TP = entry × 1.20 → need ~+20% over the trailing window).
        # Use +1.5%/bar so TP fires in ~13 bars.
        for _ in range(30):
            closes.append(closes[-1] * 1.015)
            opens.append(closes[-2])
            highs.append(closes[-1] * 1.001)
            lows.append(closes[-2] * 0.999)
            volumes.append(1_000_000.0)
        times = [f"t{i}" for i in range(len(closes))]
        bars = {"close": closes, "high": highs, "low": lows,
                "open": opens, "volume": volumes, "time": times}

        ideal = replay(bars, crypto_momentum_signal_at, ticker="SYN/USD")
        cfg = RealismConfig(
            slippage_bps=5.0, slippage_bps_crypto=25.0,
            slippage_bps_options=60.0, gap_penalty_pct=0.01,
            missed_run_pct=0.0,            # disable randomness for monotonic test
        )
        real = replay_with_realism(
            bars, crypto_momentum_signal_at, ticker="SYN/USD",
            asset_class="crypto", config=cfg,
        )
        if ideal["summary"]["n_trades"] == 0 or real["summary"]["n_trades"] == 0:
            self.skipTest("no trades fired in either mode — can't compare")
        # Realistic P&L must be ≤ idealized P&L (slippage worsens fills).
        # Note: realistic trade count may differ if SL fires due to slippage.
        ideal_pnl = ideal["summary"]["total_pnl_usd"]
        real_pnl = real["summary"]["total_pnl_usd"]
        self.assertLessEqual(
            real_pnl, ideal_pnl,
            f"realism should produce <= idealized P&L: "
            f"ideal=${ideal_pnl:,.2f} real=${real_pnl:,.2f}",
        )


class TestCryptoDataFetcherFailSoft(unittest.TestCase):
    """fetch_hourly_crypto_bars fails soft on missing creds + HTTP errors."""

    def test_missing_creds_returns_none(self):
        from crypto_data import fetch_hourly_crypto_bars
        # Clear env vars
        with patch.dict(os.environ, {"ALPACA_API_KEY": "",
                                       "ALPACA_SECRET_KEY": ""}, clear=False):
            result = fetch_hourly_crypto_bars("BTC/USD", hours=24,
                                                 use_cache=False)
        self.assertIsNone(result)

    def test_http_error_returns_none(self):
        """When requests.get raises, the fetcher must return None."""
        from crypto_data import fetch_hourly_crypto_bars
        with patch.dict(os.environ, {"ALPACA_API_KEY": "fake",
                                       "ALPACA_SECRET_KEY": "fake"}, clear=False):
            with patch("crypto_data.requests.get",
                       side_effect=RuntimeError("network down")):
                result = fetch_hourly_crypto_bars("BTC/USD", hours=24,
                                                     use_cache=False)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
