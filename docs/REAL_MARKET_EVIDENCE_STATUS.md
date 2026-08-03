# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-08-03T07:56:59.258083+00:00`
**As of:** `2026-08-03T07:56:59.188256+00:00`
**Git HEAD:** `9b18025fc7e3b82f54ee9f5783a537861542f478`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `930` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 930 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 930 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `BTC/USD` | 93 |
| `ETH/USD` | 93 |
| `SOL/USD` | 93 |
| `AVAX/USD` | 93 |
| `LINK/USD` | 93 |
| `DOT/USD` | 93 |
| `LTC/USD` | 93 |
| `BCH/USD` | 93 |
| `UNI/USD` | 93 |
| `AAVE/USD` | 93 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 930 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 930 |

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
| Last workflow run id | `30661472232` |
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
