# Near-Miss Status (v3.24.0)

**Generated:** `2026-07-31T07:22:09.269990+00:00`
**As of:** `2026-07-31T07:22:09.142982+00:00`
**Git HEAD:** `dfd23fbe1c83c8706c2dad11b529354efdb8f98a`
**Window:** last 7 days
**Tracker version:** `v3.24.0`
**Total rows ingested:** `23347`

## Operator-review flagged pairs

| (strategy, metric) pairs flagged when 95th-percentile abs distance >= `0.4` of median |threshold| AND sample >= `10` |
|---|

| Strategy | Metric | Sample | Reason |
|---|---|---|---|
| (none) | | | |

## Per-pair detail

| Strategy | Metric | Sample | p95 |dist| | Median |threshold| | Ratio | Advisory |
|---|---|---|---|---|---|---|
| `crypto-momentum` | `rsi` | 21365 | 8.7 | 60.0 | 14.5% | no |
| `crypto-oversold-bounce` | `rsi` | 1550 | 4.303794 | 30.0 | 14.3% | no |
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
