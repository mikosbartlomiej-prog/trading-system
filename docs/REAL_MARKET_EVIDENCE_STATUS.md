# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-10-25T09:18:20.708345+00:00`
**As of:** `2026-10-25T09:18:20.650428+00:00`
**Git HEAD:** `65dcabededad8a49b667115d3f1642ee62d6901c`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1095` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1095 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-breakdown` | 46 |
| `crypto-momentum` | 1019 |
| `crypto-oversold-bounce` | 30 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `ETH/USD` | 119 |
| `BTC/USD` | 112 |
| `SOL/USD` | 108 |
| `AVAX/USD` | 108 |
| `LINK/USD` | 108 |
| `DOT/USD` | 108 |
| `LTC/USD` | 108 |
| `BCH/USD` | 108 |
| `UNI/USD` | 108 |
| `AAVE/USD` | 108 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 2 |
| `0.5-0.65` | 13 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1080 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1095 |

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
| Last workflow run id | `40027854842` |
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
