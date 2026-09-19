# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-09-19T08:54:21.624319+00:00`
**As of:** `2026-09-19T08:54:21.578277+00:00`
**Git HEAD:** `36f747e51e48b90841ac9f8d6af3e77334ab45b1`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1062` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1062 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-breakdown` | 12 |
| `crypto-momentum` | 1026 |
| `crypto-oversold-bounce` | 24 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `DOT/USD` | 117 |
| `BTC/USD` | 105 |
| `ETH/USD` | 105 |
| `SOL/USD` | 105 |
| `AVAX/USD` | 105 |
| `LINK/USD` | 105 |
| `LTC/USD` | 105 |
| `BCH/USD` | 105 |
| `UNI/USD` | 105 |
| `AAVE/USD` | 105 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 12 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1050 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1062 |

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
| Last workflow run id | `35388467210` |
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
