# Replay entry-candidate discovery (v3.26.0)

**Generated:** `2026-06-15T15:03:30.166892+00:00`
**As of:** `2026-06-15T15:03:29.739374+00:00`
**Git HEAD:** `1b2a7b9825753d2e05fc7f218fafdc168709dce2`
**Lookback days:** `90`
**Snapshot dir:** `learning-loop/backfill_snapshots`

## Totals

- Candidates (replay): **29**
- Near-misses (within 15%): **138**
- Threshold crosses: **78**
- (strategy, symbol) pairs scanned: **35**

## Missing snapshots

These symbols have no cached bars at `learning-loop/backfill_snapshots`. Replay skipped — NEVER fetched live.

- `SPY` (MISSING_SNAPSHOT)
- `QQQ` (MISSING_SNAPSHOT)
- `GLD` (MISSING_SNAPSHOT)
- `AMD` (MISSING_SNAPSHOT)
- `CRWD` (MISSING_SNAPSHOT)
- `NOW` (MISSING_SNAPSHOT)
- `PANW` (MISSING_SNAPSHOT)
- `ORCL` (MISSING_SNAPSHOT)

## Per strategy + symbol

| Strategy | Symbol | Asset | Bars | Replayed | Cands | Near | Cross | Diag |
|---|---|---|---|---|---|---|---|---|
| `momentum-long` | `AAPL` | us_equity | 123 | 90 | 3 | 8 | 3 | OK |
| `momentum-long-loose` | `AAPL` | us_equity | 123 | 90 | 4 | 8 | 2 | OK |
| `overbought-short` | `AAPL` | us_equity | 123 | 90 | 2 | 3 | 6 | OK |
| `momentum-long` | `AMZN` | us_equity | 123 | 90 | 1 | 8 | 7 | OK |
| `momentum-long-loose` | `AMZN` | us_equity | 123 | 90 | 1 | 10 | 7 | OK |
| `overbought-short` | `AMZN` | us_equity | 123 | 90 | 5 | 2 | 8 | OK |
| `momentum-long` | `META` | us_equity | 123 | 90 | 0 | 7 | 5 | OK |
| `momentum-long-loose` | `META` | us_equity | 123 | 90 | 1 | 12 | 4 | OK |
| `overbought-short` | `META` | us_equity | 123 | 90 | 5 | 2 | 4 | OK |
| `momentum-long` | `MSFT` | us_equity | 123 | 90 | 0 | 5 | 4 | OK |
| `momentum-long-loose` | `MSFT` | us_equity | 123 | 90 | 0 | 11 | 4 | OK |
| `overbought-short` | `MSFT` | us_equity | 123 | 90 | 2 | 0 | 4 | OK |
| `momentum-long` | `NVDA` | us_equity | 123 | 90 | 0 | 12 | 7 | OK |
| `momentum-long-loose` | `NVDA` | us_equity | 123 | 90 | 0 | 16 | 7 | OK |
| `overbought-short` | `NVDA` | us_equity | 123 | 90 | 5 | 4 | 6 | OK |
| `crypto-momentum` | `BTC/USD` | crypto | 1637 | 90 | 0 | 0 | 0 | OK |
| `crypto-oversold-bounce` | `BTC/USD` | crypto | 1637 | 90 | 0 | 0 | 0 | OK |
| `crypto-momentum` | `ETH/USD` | crypto | 1648 | 90 | 0 | 0 | 0 | OK |
| `crypto-oversold-bounce` | `ETH/USD` | crypto | 1648 | 90 | 0 | 6 | 0 | OK |
| `crypto-momentum` | `SOL/USD` | crypto | 1624 | 90 | 0 | 0 | 0 | OK |
| `crypto-oversold-bounce` | `SOL/USD` | crypto | 1624 | 90 | 0 | 0 | 0 | OK |
| `crypto-momentum` | `LTC/USD` | crypto | 1648 | 90 | 0 | 4 | 0 | OK |
| `crypto-oversold-bounce` | `LTC/USD` | crypto | 1648 | 90 | 0 | 0 | 0 | OK |
| `crypto-momentum` | `AVAX/USD` | crypto | 1624 | 90 | 0 | 0 | 0 | OK |
| `crypto-oversold-bounce` | `AVAX/USD` | crypto | 1624 | 90 | 0 | 6 | 0 | OK |
| `crypto-momentum` | `LINK/USD` | crypto | 1636 | 90 | 0 | 0 | 0 | OK |
| `crypto-oversold-bounce` | `LINK/USD` | crypto | 1636 | 90 | 0 | 2 | 0 | OK |
| `crypto-momentum` | `DOT/USD` | crypto | 1624 | 90 | 0 | 0 | 0 | OK |
| `crypto-oversold-bounce` | `DOT/USD` | crypto | 1624 | 90 | 0 | 1 | 0 | OK |
| `crypto-momentum` | `BCH/USD` | crypto | 1636 | 90 | 0 | 4 | 0 | OK |
| `crypto-oversold-bounce` | `BCH/USD` | crypto | 1636 | 90 | 0 | 2 | 0 | OK |
| `crypto-momentum` | `UNI/USD` | crypto | 1624 | 90 | 0 | 1 | 0 | OK |
| `crypto-oversold-bounce` | `UNI/USD` | crypto | 1624 | 90 | 0 | 0 | 0 | OK |
| `crypto-momentum` | `AAVE/USD` | crypto | 1637 | 90 | 0 | 4 | 0 | OK |
| `crypto-oversold-bounce` | `AAVE/USD` | crypto | 1637 | 90 | 0 | 0 | 0 | OK |

## Safety contract

- Every record carries `evidence_source=REPLAY`.
- This script NEVER fetches live data.
- This script NEVER writes to opportunity_ledger.
- This script NEVER counts toward shadow eligibility, paper experiments, or real-market opportunities.
- This script NEVER imports `alpaca_orders`.

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
