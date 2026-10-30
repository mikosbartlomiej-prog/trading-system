# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-10-30T10:59:48.384329+00:00`
**As of:** `2026-10-30T10:59:48.299414+00:00`
**Git HEAD:** `987f7726a4b9975af1f4807635f9b9c6ca1d7971`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1293` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1293 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-breakdown` | 12 |
| `crypto-momentum` | 1255 |
| `crypto-oversold-bounce` | 26 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `LINK/USD` | 141 |
| `BTC/USD` | 128 |
| `ETH/USD` | 128 |
| `SOL/USD` | 128 |
| `AVAX/USD` | 128 |
| `DOT/USD` | 128 |
| `LTC/USD` | 128 |
| `BCH/USD` | 128 |
| `UNI/USD` | 128 |
| `AAVE/USD` | 128 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 13 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1280 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1293 |

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
| Last workflow run id | `40973588301` |
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
