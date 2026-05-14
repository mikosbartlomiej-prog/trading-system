# Learning Loop — design notes

This directory implements **continuous adaptation** of the trading system
based on its own results. Daily, after the US market close, an analyzer
reads Alpaca order history, reconstructs trades, computes per-strategy
performance, and updates `state.json`. Monitors read `state.json` at
the start of every cron run and apply the adapted parameters
(`size_multiplier`, `enabled`, `side_bias`).

**One goal:** consistently earn more.

## Files

- `analyzer.py` — daily run; reads Alpaca, reconstructs trades, calls
  `adapter` to recompute state, writes state.json + history report
  + appends rationale.md.
- `adapter.py` — pure function: `(old_state, today_stats) -> new_state`.
  Heuristic rules (cool-down on losing strategies, warm-up on winners,
  side-bias for options when puts outperform calls, etc.).
- `state.json` — current adapted parameters; checked into repo, updated
  by daily workflow via git commit.
- `rationale.md` — append-only narrative of every change ever made.
- `history/YYYY-MM-DD.md` — per-day report (full breakdown).

## state.json schema (v1.0)

```jsonc
{
  "version": "1.0",
  "last_updated": "2026-05-08T21:05:00Z",
  "days_tracked": 1,
  "cumulative": {
    "total_trades": 5,
    "total_pnl_usd": 12.34,
    "starting_equity": 100050.0
  },
  "strategies": {
    "momentum-long": {
      "trades_lifetime": 5, "trades_7d": 5,
      "win_rate_lifetime": 0.6, "win_rate_7d": 0.6,
      "pnl_usd_lifetime": 234.5, "pnl_usd_7d": 234.5,
      "size_multiplier": 1.0,    // 0.3 ≤ x ≤ 2.0
      "enabled": true,
      "side_bias": null,         // "long" | "short" | null (no bias)
      "rationale": "default — insufficient sample (need 10+ trades)"
    }
  },
  "asset_classes": {
    "stocks":  { "trades_7d": 3, "win_rate_7d": 0.66, "pnl_usd_7d": 200 },
    "crypto":  { ... },
    "options": { ... }
  },
  "sources": {
    "twitter:T1": { "follows": 5, "wins_after": 2, "win_rate": 0.4 },
    "defense:DoD": { ... }
  },
  "next_actions": [
    "options size_multiplier 1.0 -> 0.5 (3 losers in row)",
    "T3 anon traders boost 1.0 -> 1.2 (4/5 wins)"
  ],
  "global_overrides": {
    "options_side_bias": null,            // "short" pushes options to PUT-only
    "max_open_options": null,             // override docs/STRATEGY default
    "max_concurrent_per_strategy": {}     // per-strategy concurrent caps
  }
}
```

## Adapter heuristics (v1.0 starting set)

These are the initial rules. They will evolve based on observed
behavior.

| Trigger | Action |
|---|---|
| Strategy lifetime trades < 10 | Hold params (insufficient sample) |
| 7d win_rate < 35% AND ≥ 5 trades | size_multiplier *= 0.8 |
| 7d win_rate > 60% AND ≥ 5 trades | size_multiplier *= 1.10 |
| 7d P&L < -2% of equity | size_multiplier *= 0.7 (cool-down) |
| 7d P&L > +3% of equity | size_multiplier *= 1.05 (modest warm-up) |
| 5 consecutive losers | enabled = false (3-day pause) |
| Options long P&L negative AND short P&L positive | side_bias = "short" |
| Lifetime ROI < -10% | enabled = false (auto-disabled; no operator action expected) |

Bounds:
- `0.3 ≤ size_multiplier ≤ 2.0`
- `enabled` re-enables automatically after 3-day pause if next adapter
  run sees no further losses (or manual flip in state.json)

## Persistence model

Each daily-learning workflow run:
1. Reads `state.json` (current state)
2. Fetches last 24h Alpaca orders + lifetime accumulator
3. Computes new stats per strategy / asset / source
4. Calls adapter to produce new state
5. Writes `state.json`, `history/YYYY-MM-DD.md`, appends `rationale.md`
6. **git commits and pushes back to main** (uses GITHUB_TOKEN with
   contents:write permission)

This means git history IS the audit log. `git log --oneline learning-loop/state.json`
shows every adaptation ever made, with full diff per day.

## How monitors consume

```python
# In each monitor's startup:
from learning_state import load_strategy_state

state = load_strategy_state("momentum-long")  # returns dict or {}
mult = state.get("size_multiplier", 1.0)
if not state.get("enabled", True):
    return  # strategy paused by learning loop

SIZE_LONG = int(SIZE_LONG_BASE * mult)
```

For options-monitor (special — supports side_bias):
```python
state = load_strategy_state("options-momentum")
bias = state.get("side_bias")   # "short" | "long" | None
if bias == "short":
    # only consider PUT setups (RSI > 72), skip CALL
    process_only_puts = True
```

## What the analyzer tracks

Per Alpaca order:
- `client_order_id` prefix → strategy name (we set this in `shared/alpaca_orders.py`)
- `status`: filled / canceled / rejected / expired (for fill-rate analysis)
- `filled_avg_price` + qty → entry/exit valuation
- `submitted_at` / `filled_at` → hold-time analysis

Per closed trade (matched open + close):
- P&L $ and %, win/loss, hold duration, side (long/short)

Future (not in v1.0):
- Per-source attribution (which Twitter post → which trade)
- Per-news-event attribution (which RSS scrape → which trade)
- Cross-monitor signal correlation
