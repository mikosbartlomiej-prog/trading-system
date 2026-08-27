# Strategy threshold reality

**Reporter version:** v3.26.0
**Generated at (UTC):** `2026-08-27T15:25:15.407902+00:00`
**Window:** last 7 days (`20580` ledger rows scanned)

> Recommendations are **advisory only**. This module NEVER auto-adjusts a threshold, NEVER promotes a variant to active, NEVER makes a broker or network call.

## Per-strategy summary

| Strategy | Evals | Fired | Near-misses | Realism | Recommendation |
|----------|------:|------:|------------:|---------|----------------|
| `crypto-oversold-bounce` | 22 | 22 | 0 | INSUFFICIENT_DATA | OBSERVE_MORE |
| `crypto-momentum` | 20558 | 50 | 3228 | TOO_LOOSE | REPLAY_TEST_VARIANT |
| `momentum-long` | 0 | 0 | 0 | INSUFFICIENT_DATA | OBSERVE_MORE |
| `momentum-long-loose` | 0 | 0 | 0 | INSUFFICIENT_DATA | OBSERVE_MORE |
| `overbought-short` | 0 | 0 | 0 | INSUFFICIENT_DATA | OBSERVE_MORE |

## Per-metric detail

| Strategy | Metric | Threshold | Direction | Samples | Near-misses | Hits | Avg dist | Realism |
|----------|--------|-----------|-----------|--------:|------------:|-----:|---------:|---------|
| `crypto-oversold-bounce` | `rsi` | 30.0 | below | 22 | 0 | 22 | -8.5000 | INSUFFICIENT_DATA |
| `crypto-momentum` | `rsi` | 60.0 | above | 20558 | 2607 | 10331 | -0.0667 | TOO_LOOSE |
| `crypto-momentum` | `move_24h_pct` | [3.0, 15.0] | between | 20558 | 621 | 8911 | -1.3494 | REALISTIC |

## Standing safety markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `NO_THRESHOLD_AUTO_CHANGE`
- `NO_BROKER_CALL`
- `NO_PROMOTION`
- `REPORTER_VERSION=v3.26.0`

