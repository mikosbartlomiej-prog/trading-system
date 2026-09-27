# Near-Miss Status (v3.24.0)

**Generated:** `2026-09-27T10:09:04.223476+00:00`
**As of:** `2026-09-27T10:09:04.110249+00:00`
**Git HEAD:** `c9e206fbd3563adc8e2cc9236c31fb20ff9f76b3`
**Window:** last 7 days
**Tracker version:** `v3.24.0`
**Total rows ingested:** `20529`

## Operator-review flagged pairs

| (strategy, metric) pairs flagged when 95th-percentile abs distance >= `0.4` of median |threshold| AND sample >= `10` |
|---|

| Strategy | Metric | Sample | Reason |
|---|---|---|---|
| (none) | | | |

## Per-pair detail

| Strategy | Metric | Sample | p95 |dist| | Median |threshold| | Ratio | Advisory |
|---|---|---|---|---|---|---|
| `crypto-momentum` | `rsi` | 18585 | 8.5 | 60.0 | 14.2% | no |
| `crypto-oversold-bounce` | `rsi` | 1512 | 4.188034 | 30.0 | 14.0% | no |
| `overbought-short` | `rsi` | 432 | 10.585278 | 72.0 | 14.7% | no |

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
