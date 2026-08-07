# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-08-07T05:56:13.240331+00:00`
**As of:** `2026-08-07T05:56:13.179308+00:00`
**Git HEAD:** `f9c9187a5108183a98115aef47b26945c975334b`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `740` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `20` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 740 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 740 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `BTC/USD` | 74 |
| `ETH/USD` | 74 |
| `SOL/USD` | 74 |
| `AVAX/USD` | 74 |
| `LINK/USD` | 74 |
| `DOT/USD` | 74 |
| `LTC/USD` | 74 |
| `BCH/USD` | 74 |
| `UNI/USD` | 74 |
| `AAVE/USD` | 74 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 740 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 740 |

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
| Last workflow run id | `31134568295` |
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
