# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-10-29T11:02:17.326852+00:00`
**As of:** `2026-10-29T11:02:17.240420+00:00`
**Git HEAD:** `84d2eaf586210fe83b3e994752eedbf93075ac1d`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1312` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1312 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 1312 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `UNI/USD` | 142 |
| `BTC/USD` | 130 |
| `ETH/USD` | 130 |
| `SOL/USD` | 130 |
| `AVAX/USD` | 130 |
| `LINK/USD` | 130 |
| `DOT/USD` | 130 |
| `LTC/USD` | 130 |
| `BCH/USD` | 130 |
| `AAVE/USD` | 130 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 12 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1300 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1312 |

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
| Last workflow run id | `40787434242` |
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
