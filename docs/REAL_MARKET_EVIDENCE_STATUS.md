# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-06-29T09:15:37.772557+00:00`
**As of:** `2026-06-29T09:15:37.699767+00:00`
**Git HEAD:** `9502482d296ec0c2c5728cfcd2b4c5b19a33fed5`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1110` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1110 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 1110 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `BTC/USD` | 111 |
| `ETH/USD` | 111 |
| `SOL/USD` | 111 |
| `AVAX/USD` | 111 |
| `LINK/USD` | 111 |
| `DOT/USD` | 111 |
| `LTC/USD` | 111 |
| `BCH/USD` | 111 |
| `UNI/USD` | 111 |
| `AAVE/USD` | 111 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1110 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1110 |

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
| Last workflow run id | `28263040711` |
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
