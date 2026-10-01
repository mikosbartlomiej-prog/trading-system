# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-10-01T11:07:07.708762+00:00`
**As of:** `2026-10-01T11:07:07.645471+00:00`
**Git HEAD:** `bf673c37ac2f300abd9359f07f1f5403aa03a1a7`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1365` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1365 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-breakdown` | 61 |
| `crypto-momentum` | 1254 |
| `crypto-oversold-bounce` | 50 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `SOL/USD` | 147 |
| `BCH/USD` | 146 |
| `BTC/USD` | 134 |
| `ETH/USD` | 134 |
| `AVAX/USD` | 134 |
| `LINK/USD` | 134 |
| `DOT/USD` | 134 |
| `LTC/USD` | 134 |
| `UNI/USD` | 134 |
| `AAVE/USD` | 134 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 1 |
| `0.5-0.65` | 24 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1340 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1365 |

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
| Last workflow run id | `36786093365` |
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
