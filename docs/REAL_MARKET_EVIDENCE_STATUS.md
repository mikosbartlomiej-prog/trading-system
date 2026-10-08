# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-10-08T11:32:56.319784+00:00`
**As of:** `2026-10-08T11:32:56.257709+00:00`
**Git HEAD:** `158a8c446644da7b63c26f4dfc8a4b53364015fa`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1370` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1370 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 1370 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `BTC/USD` | 137 |
| `ETH/USD` | 137 |
| `SOL/USD` | 137 |
| `AVAX/USD` | 137 |
| `LINK/USD` | 137 |
| `DOT/USD` | 137 |
| `LTC/USD` | 137 |
| `BCH/USD` | 137 |
| `UNI/USD` | 137 |
| `AAVE/USD` | 137 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1370 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1370 |

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
| Last workflow run id | `37703799861` |
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
