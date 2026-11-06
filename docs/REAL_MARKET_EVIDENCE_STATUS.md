# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-11-06T12:21:52.253739+00:00`
**As of:** `2026-11-06T12:21:52.198447+00:00`
**Git HEAD:** `e1af0d58d8c4caf39b1f23b6e234e5090fa77e56`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1549` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1549 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-breakdown` | 12 |
| `crypto-momentum` | 1427 |
| `crypto-oversold-bounce` | 110 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `AVAX/USD` | 163 |
| `BTC/USD` | 162 |
| `ETH/USD` | 162 |
| `SOL/USD` | 162 |
| `LINK/USD` | 150 |
| `DOT/USD` | 150 |
| `LTC/USD` | 150 |
| `BCH/USD` | 150 |
| `UNI/USD` | 150 |
| `AAVE/USD` | 150 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 25 |
| `0.5-0.65` | 36 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1488 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1549 |

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
| Last workflow run id | `42106562537` |
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
