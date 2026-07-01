# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-07-01T08:35:47.465216+00:00`
**As of:** `2026-07-01T08:35:47.392243+00:00`
**Git HEAD:** `f5d3e51ab0d8827da688523be7a8bc21f5f4a3be`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1090` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1090 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 958 |
| `crypto-oversold-bounce` | 132 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `DOT/USD` | 139 |
| `ETH/USD` | 115 |
| `LINK/USD` | 115 |
| `BTC/USD` | 103 |
| `SOL/USD` | 103 |
| `AVAX/USD` | 103 |
| `LTC/USD` | 103 |
| `BCH/USD` | 103 |
| `UNI/USD` | 103 |
| `AAVE/USD` | 103 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 61 |
| `0.5-0.65` | 11 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1018 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1090 |

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
| Last workflow run id | `28473871063` |
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
