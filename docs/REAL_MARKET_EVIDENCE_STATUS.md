# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-11-17T13:45:07.450934+00:00`
**As of:** `2026-11-17T13:45:07.387386+00:00`
**Git HEAD:** `01bec03e7c92518aa215bb40d3f2c5d6ced30497`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1719` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1719 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-breakdown` | 119 |
| `crypto-momentum` | 1462 |
| `crypto-oversold-bounce` | 138 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `UNI/USD` | 188 |
| `DOT/USD` | 187 |
| `BTC/USD` | 177 |
| `SOL/USD` | 177 |
| `ETH/USD` | 165 |
| `AVAX/USD` | 165 |
| `LINK/USD` | 165 |
| `LTC/USD` | 165 |
| `BCH/USD` | 165 |
| `AAVE/USD` | 165 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 46 |
| `0.5-0.65` | 23 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1650 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1719 |

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
| Last workflow run id | `43975145675` |
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
