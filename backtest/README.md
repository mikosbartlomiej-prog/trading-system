# Backtest harness

Replays `momentum-long` / `overbought-short` strategies against
historical Alpaca daily bars to validate edge before deploying changes.

## Quick start

```bash
ALPACA_API_KEY=$KEY ALPACA_SECRET_KEY=$SECRET \
    python -m backtest.run \
        --strategy momentum-long \
        --tickers AAPL MSFT NVDA META \
        --days 180
```

Output:
- Per-ticker summary (trades / win rate / P&L) printed to stdout
- Aggregate stats across all tickers
- JSON ledger persisted to `backtest/results/<strategy>-<timestamp>.json`

## Files

- `data.py` — fetches daily bars from Alpaca `/v2/stocks/{sym}/bars` (free
  IEX feed, paginated). Caches to `backtest/.cache/<sym>-<start>-<end>.json`
  so repeated runs don't hit the API.
- `strategies.py` — pure-function signal logic mirroring
  `price-monitor/monitor.py::check_long_signal` /
  `check_short_signal`. Each `*_signal_at(idx, bars)` is a pure function
  returning `None` (no signal) or a dict (entry/SL/TP/RSI/ATR).
- `replay.py` — walk-forward replay loop. One position at a time per
  ticker. Bracket simulated by checking next-day H/L against TP/SL.
  No slippage / commission modelled (paper baseline).
- `run.py` — CLI entry point.
- `results/` — JSON ledgers (gitignored — these can be huge)
- `.cache/` — bar data cache (gitignored)

## What this does NOT do (yet)

- Multi-position per ticker (e.g. pyramiding) — single-position only.
- Time-based exits beyond TP/SL — relies on bracket levels.
- Slippage / commission / spread modelling — assumes clean fills at SL/TP.
- Asset classes other than US stocks via daily bars — no crypto, no
  options, no intraday bars (would need `1Hour`/`5Min` timeframe).
- Walk-forward parameter optimization — strategy params are fixed to
  match `STRATEGY.md` §4.1-4.2.

## Interpreting results

For a strategy with positive edge over 6 months on the whitelist:
- `win_rate` should be ≥ 40% (R:R 2.0 means low win rate is OK)
- `total_pnl_usd` should be positive across the basket
- `avg_pnl_pct` should be positive
- if `worst_pct < -10%` consistently → SL too wide, tighten ATR_SL_MULT

If a strategy looks bad here but works live — likely due to live signal
being intraday-triggered while we replay on daily bars. Daily replay is
a sanity check, not perfect simulation.

## Smoke test

A synthetic-bar smoke test verifies the harness doesn't lose money on
known-good price patterns:

```bash
# In a clean checkout (no Alpaca creds needed for the synthetic test):
python -c "
import sys; sys.path.insert(0, 'backtest')
from strategies import momentum_long_signal_at
from replay import replay
# build synthetic bars + replay — see git history for full fixture
"
```

The smoke test in commit `<this commit>` replays a 60-day pattern
(range → breakout → pullback → rip) and verifies the long strategy
catches the breakout for a +3.8% win.
