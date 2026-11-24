# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-11-24T15:08:35.683581+00:00`
**As of:** `2026-11-24T15:08:35.595337+00:00`
**Git HEAD:** `a7dc4c3ee559c9184d2d8aff3aa99fda5a22e952`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1780` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `20` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1780 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-breakdown` | 36 |
| `crypto-momentum` | 1744 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `BTC/USD` | 178 |
| `ETH/USD` | 178 |
| `SOL/USD` | 178 |
| `AVAX/USD` | 178 |
| `LINK/USD` | 178 |
| `DOT/USD` | 178 |
| `LTC/USD` | 178 |
| `BCH/USD` | 178 |
| `UNI/USD` | 178 |
| `AAVE/USD` | 178 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1780 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1780 |

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
| Last workflow run id | `45302800806` |
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
