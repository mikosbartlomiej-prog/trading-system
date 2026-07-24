# Replay entry-candidate discovery (v3.26.0)

**Generated:** `2026-07-24T07:08:00.327129+00:00`
**As of:** `2026-07-24T07:08:00.255657+00:00`
**Git HEAD:** `2bf5953027a638e186a309dbed5f386289d4d1e7`
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
| `crypto-momentum` | `BTC/USD` | crypto | 5000 | 7 | 0 | 0 | 0 | OK |
| `crypto-oversold-bounce` | `BTC/USD` | crypto | 5000 | 7 | 0 | 0 | 0 | OK |
| `crypto-momentum` | `ETH/USD` | crypto | 5000 | 7 | 0 | 0 | 0 | OK |
| `crypto-oversold-bounce` | `ETH/USD` | crypto | 5000 | 7 | 0 | 0 | 0 | OK |
| `crypto-momentum` | `SOL/USD` | crypto | 5000 | 7 | 0 | 0 | 0 | OK |
| `crypto-oversold-bounce` | `SOL/USD` | crypto | 5000 | 7 | 0 | 0 | 0 | OK |
| `crypto-momentum` | `LTC/USD` | crypto | 5000 | 7 | 0 | 0 | 0 | OK |
| `crypto-oversold-bounce` | `LTC/USD` | crypto | 5000 | 7 | 0 | 0 | 0 | OK |
| `crypto-momentum` | `AVAX/USD` | crypto | 5000 | 7 | 0 | 0 | 0 | OK |
| `crypto-oversold-bounce` | `AVAX/USD` | crypto | 5000 | 7 | 0 | 0 | 0 | OK |

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
