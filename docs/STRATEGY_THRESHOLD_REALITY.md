# Strategy threshold reality

**Reporter version:** v3.26.0
**Generated at (UTC):** `2026-07-09T08:01:56.824850+00:00`
**Window:** last 7 days (`18708` ledger rows scanned)

> Recommendations are **advisory only**. This module NEVER auto-adjusts a threshold, NEVER promotes a variant to active, NEVER makes a broker or network call.

## Per-strategy summary

| Strategy | Evals | Fired | Near-misses | Realism | Recommendation |
|----------|------:|------:|------------:|---------|----------------|
| `crypto-oversold-bounce` | 202 | 202 | 0 | TOO_LOOSE | REPLAY_TEST_VARIANT |
| `crypto-momentum` | 18506 | 102 | 3405 | REALISTIC | KEEP |
| `momentum-long` | 0 | 0 | 0 | INSUFFICIENT_DATA | OBSERVE_MORE |
| `momentum-long-loose` | 0 | 0 | 0 | INSUFFICIENT_DATA | OBSERVE_MORE |
| `overbought-short` | 0 | 0 | 0 | INSUFFICIENT_DATA | OBSERVE_MORE |

## Per-metric detail

| Strategy | Metric | Threshold | Direction | Samples | Near-misses | Hits | Avg dist | Realism |
|----------|--------|-----------|-----------|--------:|------------:|-----:|---------:|---------|
| `crypto-oversold-bounce` | `rsi` | 30.0 | below | 202 | 0 | 202 | -4.7248 | TOO_LOOSE |
| `crypto-momentum` | `rsi` | 60.0 | above | 18506 | 2780 | 7601 | -5.5516 | REALISTIC |
| `crypto-momentum` | `move_24h_pct` | [3.0, 15.0] | between | 18506 | 625 | 3621 | -2.2043 | REALISTIC |

## Standing safety markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `NO_THRESHOLD_AUTO_CHANGE`
- `NO_BROKER_CALL`
- `NO_PROMOTION`
- `REPORTER_VERSION=v3.26.0`

