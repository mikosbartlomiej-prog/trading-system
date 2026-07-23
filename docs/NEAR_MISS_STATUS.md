# Near-Miss Status (v3.24.0)

**Generated:** `2026-07-23T07:05:47.646871+00:00`
**As of:** `2026-07-23T07:05:47.541941+00:00`
**Git HEAD:** `fca75c0cd5fba9f8ae61fbec4ac5b65ff2e2091b`
**Window:** last 7 days
**Tracker version:** `v3.24.0`
**Total rows ingested:** `17172`

## Operator-review flagged pairs

| (strategy, metric) pairs flagged when 95th-percentile abs distance >= `0.4` of median |threshold| AND sample >= `10` |
|---|

| Strategy | Metric | Sample | Reason |
|---|---|---|---|
| (none) | | | |

## Per-pair detail

| Strategy | Metric | Sample | p95 |dist| | Median |threshold| | Ratio | Advisory |
|---|---|---|---|---|---|---|
| `crypto-momentum` | `rsi` | 16016 | 8.648649 | 60.0 | 14.4% | no |
| `crypto-oversold-bounce` | `rsi` | 868 | 4.303794 | 30.0 | 14.3% | no |
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
