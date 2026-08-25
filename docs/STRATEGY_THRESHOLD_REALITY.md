# Strategy threshold reality

**Reporter version:** v3.26.0
**Generated at (UTC):** `2026-08-25T05:06:06.704547+00:00`
**Window:** last 7 days (`19822` ledger rows scanned)

> Recommendations are **advisory only**. This module NEVER auto-adjusts a threshold, NEVER promotes a variant to active, NEVER makes a broker or network call.

## Per-strategy summary

| Strategy | Evals | Fired | Near-misses | Realism | Recommendation |
|----------|------:|------:|------------:|---------|----------------|
| `crypto-oversold-bounce` | 184 | 184 | 0 | TOO_LOOSE | REPLAY_TEST_VARIANT |
| `crypto-momentum` | 19638 | 26 | 3137 | TOO_LOOSE | REPLAY_TEST_VARIANT |
| `momentum-long` | 0 | 0 | 0 | INSUFFICIENT_DATA | OBSERVE_MORE |
| `momentum-long-loose` | 0 | 0 | 0 | INSUFFICIENT_DATA | OBSERVE_MORE |
| `overbought-short` | 0 | 0 | 0 | INSUFFICIENT_DATA | OBSERVE_MORE |

## Per-metric detail

| Strategy | Metric | Threshold | Direction | Samples | Near-misses | Hits | Avg dist | Realism |
|----------|--------|-----------|-----------|--------:|------------:|-----:|---------:|---------|
| `crypto-oversold-bounce` | `rsi` | 30.0 | below | 184 | 0 | 184 | -8.2522 | TOO_LOOSE |
| `crypto-momentum` | `rsi` | 60.0 | above | 19638 | 2739 | 10660 | 1.2201 | TOO_LOOSE |
| `crypto-momentum` | `move_24h_pct` | [3.0, 15.0] | between | 19638 | 398 | 7625 | -1.2869 | REALISTIC |

## Standing safety markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `NO_THRESHOLD_AUTO_CHANGE`
- `NO_BROKER_CALL`
- `NO_PROMOTION`
- `REPORTER_VERSION=v3.26.0`

