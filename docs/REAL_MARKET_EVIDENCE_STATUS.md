# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-10-19T10:09:34.728535+00:00`
**As of:** `2026-10-19T10:09:34.651859+00:00`
**Git HEAD:** `816cec86c7e0301aa2b6cdfb335b326df320b60c`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1222` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1222 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 1222 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `ETH/USD` | 133 |
| `BTC/USD` | 121 |
| `SOL/USD` | 121 |
| `AVAX/USD` | 121 |
| `LINK/USD` | 121 |
| `DOT/USD` | 121 |
| `LTC/USD` | 121 |
| `BCH/USD` | 121 |
| `UNI/USD` | 121 |
| `AAVE/USD` | 121 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 12 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1210 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1222 |

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
| Last workflow run id | `38970415770` |
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
