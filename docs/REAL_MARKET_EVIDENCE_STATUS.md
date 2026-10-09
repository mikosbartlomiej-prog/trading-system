# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-10-09T11:28:13.671136+00:00`
**As of:** `2026-10-09T11:28:13.596162+00:00`
**Git HEAD:** `3093858795c61b7d842621ccc3ede251f8111c49`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1351` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1351 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 1329 |
| `crypto-oversold-bounce` | 22 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `UNI/USD` | 145 |
| `BTC/USD` | 134 |
| `ETH/USD` | 134 |
| `SOL/USD` | 134 |
| `AVAX/USD` | 134 |
| `LINK/USD` | 134 |
| `DOT/USD` | 134 |
| `LTC/USD` | 134 |
| `BCH/USD` | 134 |
| `AAVE/USD` | 134 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 11 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1340 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1351 |

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
| Last workflow run id | `37861800033` |
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
