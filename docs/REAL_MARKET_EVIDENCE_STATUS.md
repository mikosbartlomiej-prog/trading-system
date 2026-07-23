# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-07-23T07:05:46.995507+00:00`
**As of:** `2026-07-23T07:05:46.923922+00:00`
**Git HEAD:** `fca75c0cd5fba9f8ae61fbec4ac5b65ff2e2091b`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `860` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 860 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 860 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `BTC/USD` | 86 |
| `ETH/USD` | 86 |
| `SOL/USD` | 86 |
| `AVAX/USD` | 86 |
| `LINK/USD` | 86 |
| `DOT/USD` | 86 |
| `LTC/USD` | 86 |
| `BCH/USD` | 86 |
| `UNI/USD` | 86 |
| `AAVE/USD` | 86 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 860 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 860 |

## Data-failure signature (latest workflow_health diagnostic_token_counts)

| Token | Count |
|---|---|
| (none) | 0 |

## Progress toward N=50 unlock

| Metric | Value |
|---|---|
| `real_market_opportunities_count` (lifetime) | `0` |
| Target | `50` |
| Rolling window (days) | `3` |
| Rolling avg opportunities/day | `0.000` |
| Estimated days to N=50 | `UNKNOWN` |

## Workflow context

| Field | Value |
|---|---|
| Last workflow run id | `29956083685` |
| Last workflow run conclusion | `success` |
| Last collector status | `SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA` |
| Secrets status | `SECRETS_AVAILABLE` |

## Safety invariants

- `edge_gate_enabled`: `false`
- `allow_broker_paper`: `false`
- `live_trading_supported`: `false`
- `observations_count_as_opportunities`: `false`

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
