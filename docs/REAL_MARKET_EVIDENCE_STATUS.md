# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-08-23T05:01:54.555313+00:00`
**As of:** `2026-08-23T05:01:54.499989+00:00`
**Git HEAD:** `e93136a9df69c3025afdbba82b46ea2ec035fcd5`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `650` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 650 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 650 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `BTC/USD` | 65 |
| `ETH/USD` | 65 |
| `SOL/USD` | 65 |
| `AVAX/USD` | 65 |
| `LINK/USD` | 65 |
| `DOT/USD` | 65 |
| `LTC/USD` | 65 |
| `BCH/USD` | 65 |
| `UNI/USD` | 65 |
| `AAVE/USD` | 65 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 650 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 650 |

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
| Last workflow run id | `32520396463` |
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
