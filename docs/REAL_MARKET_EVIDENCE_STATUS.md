# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-08-21T05:05:08.571868+00:00`
**As of:** `2026-08-21T05:05:08.506732+00:00`
**Git HEAD:** `d8182569010b84ec584e4948481fc21de33b3dd6`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `640` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 640 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-breakdown` | 12 |
| `crypto-momentum` | 628 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `BTC/USD` | 64 |
| `ETH/USD` | 64 |
| `SOL/USD` | 64 |
| `AVAX/USD` | 64 |
| `LINK/USD` | 64 |
| `DOT/USD` | 64 |
| `LTC/USD` | 64 |
| `BCH/USD` | 64 |
| `UNI/USD` | 64 |
| `AAVE/USD` | 64 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 640 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 640 |

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
| Last workflow run id | `32411414581` |
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
