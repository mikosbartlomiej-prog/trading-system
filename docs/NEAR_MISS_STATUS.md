# Near-Miss Status (v3.24.0)

**Generated:** `2026-08-24T05:12:12.804032+00:00`
**As of:** `2026-08-24T05:12:12.681957+00:00`
**Git HEAD:** `64bb44d9ea73a42d2cea1d325053ad5256a08c7c`
**Window:** last 7 days
**Tracker version:** `v3.24.0`
**Total rows ingested:** `19371`

## Operator-review flagged pairs

| (strategy, metric) pairs flagged when 95th-percentile abs distance >= `0.4` of median |threshold| AND sample >= `10` |
|---|

| Strategy | Metric | Sample | Reason |
|---|---|---|---|
| (none) | | | |

## Per-pair detail

| Strategy | Metric | Sample | p95 |dist| | Median |threshold| | Ratio | Advisory |
|---|---|---|---|---|---|---|
| `crypto-momentum` | `rsi` | 18433 | 8.7 | 60.0 | 14.5% | no |
| `crypto-oversold-bounce` | `rsi` | 650 | 3.88832 | 30.0 | 13.0% | no |
| `overbought-short` | `rsi` | 288 | 10.585278 | 72.0 | 14.7% | no |

## Safety contract

- Each near-miss record carries `is_paper_trade=False`, `is_signal=False`.
- This reporter NEVER auto-adjusts a strategy threshold.
- This reporter NEVER places orders.

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `NEAR_MISS_NEVER_COUNTS_AS_TRADE`
- `NEAR_MISS_NEVER_AUTO_ADJUSTS_THRESHOLDS`
