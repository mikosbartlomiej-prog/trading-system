# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-06-22T10:21:45.441508+00:00`
**As of:** `2026-06-22T10:21:45.356701+00:00`
**Git HEAD:** `8e6ad465f974797eaeff9ab7b916c9b56320ed4c`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1253` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1253 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 1207 |
| `crypto-oversold-bounce` | 46 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `SOL/USD` | 135 |
| `BTC/USD` | 134 |
| `ETH/USD` | 123 |
| `AVAX/USD` | 123 |
| `LINK/USD` | 123 |
| `DOT/USD` | 123 |
| `LTC/USD` | 123 |
| `BCH/USD` | 123 |
| `UNI/USD` | 123 |
| `AAVE/USD` | 123 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 23 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1230 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1253 |

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
| Last workflow run id | `27846567032` |
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
