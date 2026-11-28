# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-11-28T13:27:52.038496+00:00`
**As of:** `2026-11-28T13:27:51.979347+00:00`
**Git HEAD:** `54ba40e71075af6dfc6dd67ee93bc6a30590e401`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1610` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1610 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-breakdown` | 72 |
| `crypto-momentum` | 1538 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `BTC/USD` | 161 |
| `ETH/USD` | 161 |
| `SOL/USD` | 161 |
| `AVAX/USD` | 161 |
| `LINK/USD` | 161 |
| `DOT/USD` | 161 |
| `LTC/USD` | 161 |
| `BCH/USD` | 161 |
| `UNI/USD` | 161 |
| `AAVE/USD` | 161 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1610 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1610 |

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
| Last workflow run id | `46075523658` |
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
