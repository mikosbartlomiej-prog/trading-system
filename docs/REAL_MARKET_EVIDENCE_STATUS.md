# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-11-25T14:48:29.714648+00:00`
**As of:** `2026-11-25T14:48:29.641924+00:00`
**Git HEAD:** `20959f95879b6ce17009ea630edbd6acaceb9ce8`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1734` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1734 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 1710 |
| `crypto-oversold-bounce` | 24 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `ETH/USD` | 183 |
| `LTC/USD` | 183 |
| `BTC/USD` | 171 |
| `SOL/USD` | 171 |
| `AVAX/USD` | 171 |
| `LINK/USD` | 171 |
| `DOT/USD` | 171 |
| `BCH/USD` | 171 |
| `UNI/USD` | 171 |
| `AAVE/USD` | 171 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 24 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1710 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1734 |

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
| Last workflow run id | `45508024923` |
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
