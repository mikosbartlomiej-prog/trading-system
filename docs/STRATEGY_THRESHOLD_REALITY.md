# Strategy threshold reality

**Reporter version:** v3.26.0
**Generated at (UTC):** `2026-11-18T13:20:29.753669+00:00`
**Window:** last 7 days (`18420` ledger rows scanned)

> Recommendations are **advisory only**. This module NEVER auto-adjusts a threshold, NEVER promotes a variant to active, NEVER makes a broker or network call.

## Per-strategy summary

| Strategy | Evals | Fired | Near-misses | Realism | Recommendation |
|----------|------:|------:|------------:|---------|----------------|
| `crypto-oversold-bounce` | 814 | 814 | 0 | TOO_LOOSE | REPLAY_TEST_VARIANT |
| `crypto-momentum` | 17606 | 24 | 1636 | REALISTIC | KEEP |
| `momentum-long` | 0 | 0 | 0 | INSUFFICIENT_DATA | OBSERVE_MORE |
| `momentum-long-loose` | 0 | 0 | 0 | INSUFFICIENT_DATA | OBSERVE_MORE |
| `overbought-short` | 0 | 0 | 0 | INSUFFICIENT_DATA | OBSERVE_MORE |

## Per-metric detail

| Strategy | Metric | Threshold | Direction | Samples | Near-misses | Hits | Avg dist | Realism |
|----------|--------|-----------|-----------|--------:|------------:|-----:|---------:|---------|
| `crypto-oversold-bounce` | `rsi` | 30.0 | below | 814 | 0 | 814 | -6.5204 | TOO_LOOSE |
| `crypto-momentum` | `rsi` | 60.0 | above | 17606 | 1554 | 2426 | -18.4760 | REALISTIC |
| `crypto-momentum` | `move_24h_pct` | [3.0, 15.0] | between | 17606 | 82 | 700 | -5.7453 | REALISTIC |

## Standing safety markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `NO_THRESHOLD_AUTO_CHANGE`
- `NO_BROKER_CALL`
- `NO_PROMOTION`
- `REPORTER_VERSION=v3.26.0`

