# Strategy threshold reality

**Reporter version:** v3.26.0
**Generated at (UTC):** `2026-09-26T09:29:51.233161+00:00`
**Window:** last 7 days (`18384` ledger rows scanned)

> Recommendations are **advisory only**. This module NEVER auto-adjusts a threshold, NEVER promotes a variant to active, NEVER makes a broker or network call.

## Per-strategy summary

| Strategy | Evals | Fired | Near-misses | Realism | Recommendation |
|----------|------:|------:|------------:|---------|----------------|
| `crypto-oversold-bounce` | 94 | 94 | 0 | TOO_LOOSE | REPLAY_TEST_VARIANT |
| `crypto-momentum` | 18290 | 0 | 2626 | TOO_LOOSE | SHADOW_VARIANT_REVIEW |
| `momentum-long` | 0 | 0 | 0 | INSUFFICIENT_DATA | OBSERVE_MORE |
| `momentum-long-loose` | 0 | 0 | 0 | INSUFFICIENT_DATA | OBSERVE_MORE |
| `overbought-short` | 0 | 0 | 0 | INSUFFICIENT_DATA | OBSERVE_MORE |

## Per-metric detail

| Strategy | Metric | Threshold | Direction | Samples | Near-misses | Hits | Avg dist | Realism |
|----------|--------|-----------|-----------|--------:|------------:|-----:|---------:|---------|
| `crypto-oversold-bounce` | `rsi` | 30.0 | below | 94 | 0 | 94 | -1.8447 | TOO_LOOSE |
| `crypto-momentum` | `rsi` | 60.0 | above | 18290 | 1881 | 10516 | 1.6716 | TOO_LOOSE |
| `crypto-momentum` | `move_24h_pct` | [3.0, 15.0] | between | 18290 | 745 | 8317 | -1.0893 | REALISTIC |

## Standing safety markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `NO_THRESHOLD_AUTO_CHANGE`
- `NO_BROKER_CALL`
- `NO_PROMOTION`
- `REPORTER_VERSION=v3.26.0`

