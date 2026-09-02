# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-09-02T08:57:20.253187+00:00`
**As of:** `2026-09-02T08:57:20.189809+00:00`
**Git HEAD:** `9e50f273002e8fde104dceda2bb5d761921e73ef`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1090` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1090 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 1090 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `BTC/USD` | 109 |
| `ETH/USD` | 109 |
| `SOL/USD` | 109 |
| `AVAX/USD` | 109 |
| `LINK/USD` | 109 |
| `DOT/USD` | 109 |
| `LTC/USD` | 109 |
| `BCH/USD` | 109 |
| `UNI/USD` | 109 |
| `AAVE/USD` | 109 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1090 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1090 |

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
| Last workflow run id | `33553340158` |
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
