# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-11-09T13:13:49.925950+00:00`
**As of:** `2026-11-09T13:13:49.863492+00:00`
**Git HEAD:** `f4ad55cab0e2fff7f1ab613111b24dd77e2832c3`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1580` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1580 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 1560 |
| `crypto-oversold-bounce` | 20 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `SOL/USD` | 167 |
| `BTC/USD` | 157 |
| `ETH/USD` | 157 |
| `AVAX/USD` | 157 |
| `LINK/USD` | 157 |
| `DOT/USD` | 157 |
| `LTC/USD` | 157 |
| `BCH/USD` | 157 |
| `UNI/USD` | 157 |
| `AAVE/USD` | 157 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 10 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1570 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1580 |

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
