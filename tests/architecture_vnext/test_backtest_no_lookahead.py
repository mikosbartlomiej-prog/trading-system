"""v3.10 Phase F — no-lookahead invariant for backtest signal functions.

A signal function must produce the SAME signal for a given (bars[:idx])
slice regardless of what comes after idx. If a signal changes when future
bars are added, the strategy is leaking future data into the present decision
(lookahead bias). Such strategies generate fake alpha in backtest that
disappears in live trading.

This test:
1. Generates synthetic bars
2. For each signal function in SIGNALS dict:
   a. Computes signal at idx=N using bars[0:N]
   b. Computes signal at idx=N using bars[0:N+5] (more future data)
   c. Asserts signal_a == signal_b (no lookahead)
"""

import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import _path  # noqa: F401

import unittest


def _synthetic_bars(n=100, seed=42):
    """Deterministic synthetic OHLCV bars (geometric brownian)."""
    import math, random
    random.seed(seed)
    close = [100.0]
    for _ in range(n - 1):
        # ±2% daily move
        close.append(close[-1] * (1 + (random.random() - 0.5) * 0.04))
    open_ = [close[0]] + close[:-1]
    high = [max(o, c) * 1.005 for o, c in zip(open_, close)]
    low = [min(o, c) * 0.995 for o, c in zip(open_, close)]
    vol = [1_000_000 + int(random.random() * 500_000) for _ in range(n)]
    return {
        "open": open_, "high": high, "low": low, "close": close, "volume": vol,
        "timestamp": [f"2026-01-{(i % 28) + 1:02d}T13:30:00Z" for i in range(n)],
    }


def _slice_bars(bars, end_idx):
    """Return bars dict truncated to [0:end_idx]."""
    return {k: (v[:end_idx] if isinstance(v, list) else v) for k, v in bars.items()}


class TestNoLookahead(unittest.TestCase):
    """Each signal function MUST produce identical output for bars[0:N] vs
    bars[0:N+k] when queried at position N. Otherwise it leaks future data."""

    def setUp(self):
        # Late import so backtest/ sys.path is set
        sys.path.insert(
            0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backtest")),
        )
        from strategies import (
            momentum_long_signal_at,
            momentum_long_loose_signal_at,
            overbought_short_signal_at,
        )
        self.signal_fns = {
            "momentum-long":       momentum_long_signal_at,
            "momentum-long-loose": momentum_long_loose_signal_at,
            "overbought-short":    overbought_short_signal_at,
        }
        self.bars_full = _synthetic_bars(n=80)

    def test_no_lookahead_at_various_indices(self):
        """For each signal function and each idx in [30, 40, 50, 60, 70],
        signal at idx using full bars must equal signal at idx using
        truncated bars[0:idx+1]. If they differ → lookahead bias."""
        for name, fn in self.signal_fns.items():
            for idx in [30, 40, 50, 60, 70]:
                # Truncated: only data up to idx+1 (inclusive of current bar)
                truncated = _slice_bars(self.bars_full, idx + 1)
                # Full bars but querying at same idx
                sig_truncated = fn(idx, truncated)
                sig_full = fn(idx, self.bars_full)
                self.assertEqual(
                    sig_truncated, sig_full,
                    f"LOOKAHEAD detected in '{name}' at idx={idx}: "
                    f"truncated={sig_truncated} vs full={sig_full}",
                )

    def test_signal_returns_consistent_shape(self):
        """Each signal function returns None or dict (no surprise types)."""
        for name, fn in self.signal_fns.items():
            for idx in [10, 50]:
                out = fn(idx, self.bars_full)
                self.assertTrue(
                    out is None or isinstance(out, dict),
                    f"{name} at idx={idx} returned {type(out).__name__}; expected None or dict",
                )


if __name__ == "__main__":
    unittest.main()
