# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-07-11T06:35:38.902722+00:00`
**As of:** `2026-07-11T06:35:38.836799+00:00`
**Git HEAD:** `bee645ed13690140ef1600b75601d994542678e5`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `861` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 861 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-breakdown` | 27 |
| `crypto-momentum` | 732 |
| `crypto-oversold-bounce` | 102 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `DOT/USD` | 106 |
| `AVAX/USD` | 94 |
| `LTC/USD` | 94 |
| `BTC/USD` | 81 |
| `ETH/USD` | 81 |
| `SOL/USD` | 81 |
| `LINK/USD` | 81 |
| `BCH/USD` | 81 |
| `UNI/USD` | 81 |
| `AAVE/USD` | 81 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 38 |
| `0.5-0.65` | 13 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 810 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 861 |

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
| Last workflow run id | `29119892885` |
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
