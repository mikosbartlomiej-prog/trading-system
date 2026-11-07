# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-11-07T11:16:01.211272+00:00`
**As of:** `2026-11-07T11:16:01.145678+00:00`
**Git HEAD:** `c0b0b5f9757f9f3319a32940158e93ab0ad1ed07`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1342` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1342 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 1342 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `AVAX/USD` | 145 |
| `BTC/USD` | 133 |
| `ETH/USD` | 133 |
| `SOL/USD` | 133 |
| `LINK/USD` | 133 |
| `DOT/USD` | 133 |
| `LTC/USD` | 133 |
| `BCH/USD` | 133 |
| `UNI/USD` | 133 |
| `AAVE/USD` | 133 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 12 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1330 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1342 |

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
| Last workflow run id | `42284827295` |
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
