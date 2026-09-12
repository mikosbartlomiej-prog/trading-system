# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-09-12T08:45:34.351026+00:00`
**As of:** `2026-09-12T08:45:34.288951+00:00`
**Git HEAD:** `f45fd7fca40857dd98d6d425b308dd1c8d2fca84`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1010` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1010 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 1010 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `BTC/USD` | 101 |
| `ETH/USD` | 101 |
| `SOL/USD` | 101 |
| `AVAX/USD` | 101 |
| `LINK/USD` | 101 |
| `DOT/USD` | 101 |
| `LTC/USD` | 101 |
| `BCH/USD` | 101 |
| `UNI/USD` | 101 |
| `AAVE/USD` | 101 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1010 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1010 |

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
| Last workflow run id | `34641659725` |
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
