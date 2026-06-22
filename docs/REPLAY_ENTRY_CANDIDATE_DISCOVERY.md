# Replay entry-candidate discovery (v3.26.0)

**Generated:** `2026-06-22T10:22:04.078910+00:00`
**As of:** `2026-06-22T10:22:04.029377+00:00`
**Git HEAD:** `8e6ad465f974797eaeff9ab7b916c9b56320ed4c`
**Lookback days:** `7`
**Snapshot dir:** `learning-loop/backfill_snapshots`

## Totals

- Candidates (replay): **0**
- Near-misses (within 15%): **0**
- Threshold crosses: **0**
- (strategy, symbol) pairs scanned: **10**

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
| `crypto-momentum` | `BTC/USD` | crypto | 3503 | 7 | 0 | 0 | 0 | OK |
| `crypto-oversold-bounce` | `BTC/USD` | crypto | 3503 | 7 | 0 | 0 | 0 | OK |
| `crypto-momentum` | `ETH/USD` | crypto | 3516 | 7 | 0 | 0 | 0 | OK |
| `crypto-oversold-bounce` | `ETH/USD` | crypto | 3516 | 7 | 0 | 0 | 0 | OK |
| `crypto-momentum` | `SOL/USD` | crypto | 3503 | 7 | 0 | 0 | 0 | OK |
| `crypto-oversold-bounce` | `SOL/USD` | crypto | 3503 | 7 | 0 | 0 | 0 | OK |
| `crypto-momentum` | `LTC/USD` | crypto | 3516 | 7 | 0 | 0 | 0 | OK |
| `crypto-oversold-bounce` | `LTC/USD` | crypto | 3516 | 7 | 0 | 0 | 0 | OK |
| `crypto-momentum` | `AVAX/USD` | crypto | 3490 | 7 | 0 | 0 | 0 | OK |
| `crypto-oversold-bounce` | `AVAX/USD` | crypto | 3490 | 7 | 0 | 0 | 0 | OK |

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
