# Backfill snapshot status (v3.27.0)

**Generated:** `2026-06-18T09:00:53.580233+00:00`
**Git HEAD:** `e9545b98a138e72e7525cac3b5a48e392b179e91`
**Snapshot dir:** `learning-loop/backfill_snapshots`

## Status: `LEDGER_DERIVED_PARTIAL`

## Totals

- Snapshots written: **10**
- Partial-bars snapshots: **10** (missing one or more of `high`/`low`/`volume`/`open`)
- From backtest cache (REAL OHLCV): **0**
- From opportunity ledger (partial): **10**
- From shadow evidence (partial): **0**

## Source label distribution

- `LEDGER_DERIVED_REPLAY_ONLY` × **10**

## Per-symbol summary

| Symbol | Source | Quality | Bars | Partial | Min fields |
|---|---|---|---|---|---|
| `AAVE/USD` | LEDGER_DERIVED_REPLAY_ONLY | PARTIAL_BARS | 2296 | True | False |
| `AVAX/USD` | LEDGER_DERIVED_REPLAY_ONLY | PARTIAL_BARS | 2283 | True | False |
| `BCH/USD` | LEDGER_DERIVED_REPLAY_ONLY | PARTIAL_BARS | 2319 | True | False |
| `BTC/USD` | LEDGER_DERIVED_REPLAY_ONLY | PARTIAL_BARS | 2296 | True | False |
| `DOT/USD` | LEDGER_DERIVED_REPLAY_ONLY | PARTIAL_BARS | 2283 | True | False |
| `ETH/USD` | LEDGER_DERIVED_REPLAY_ONLY | PARTIAL_BARS | 2307 | True | False |
| `LINK/USD` | LEDGER_DERIVED_REPLAY_ONLY | PARTIAL_BARS | 2307 | True | False |
| `LTC/USD` | LEDGER_DERIVED_REPLAY_ONLY | PARTIAL_BARS | 2307 | True | False |
| `SOL/USD` | LEDGER_DERIVED_REPLAY_ONLY | PARTIAL_BARS | 2295 | True | False |
| `UNI/USD` | LEDGER_DERIVED_REPLAY_ONLY | PARTIAL_BARS | 2283 | True | False |

## Safety contract

- Seeder NEVER fetches live market data.
- Seeder NEVER fabricates synthetic OHLCV.
- Seeder NEVER imports `alpaca_orders`.
- Seeder NEVER writes to opportunity_ledger / paper_experiments / state.json.
- All snapshots carry `mode=REPLAY_ONLY`, `is_paper_trade=False`, `is_real_market_evidence=False`.

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `REPLAY_NEVER_COUNTS_AS_PAPER`
- `REPLAY_NEVER_COUNTS_AS_REAL_MARKET`
- `REPLAY_NEVER_AUTO_ENABLES_STRATEGY`
- `SEEDER_DOES_NOT_FABRICATE_OHLCV`
- `SEEDER_DOES_NOT_FETCH_NETWORK`
