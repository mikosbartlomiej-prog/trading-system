# Near-Miss Status (v3.24.0)

**Generated:** `2026-09-06T08:47:30.178143+00:00`
**As of:** `2026-09-06T08:47:30.061704+00:00`
**Git HEAD:** `447169e966719c6a612c315dc452ab8cdf7215b3`
**Window:** last 7 days
**Tracker version:** `v3.24.0`
**Total rows ingested:** `20858`

## Operator-review flagged pairs

| (strategy, metric) pairs flagged when 95th-percentile abs distance >= `0.4` of median |threshold| AND sample >= `10` |
|---|

| Strategy | Metric | Sample | Reason |
|---|---|---|---|
| (none) | | | |

## Per-pair detail

| Strategy | Metric | Sample | p95 |dist| | Median |threshold| | Ratio | Advisory |
|---|---|---|---|---|---|---|
| `crypto-momentum` | `rsi` | 19586 | 8.7 | 60.0 | 14.5% | no |
| `crypto-oversold-bounce` | `rsi` | 912 | 3.858268 | 30.0 | 12.9% | no |
| `overbought-short` | `rsi` | 360 | 10.585278 | 72.0 | 14.7% | no |

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
