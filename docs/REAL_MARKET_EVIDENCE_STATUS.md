# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-07-05T07:43:43.827759+00:00`
**As of:** `2026-07-05T07:43:43.756903+00:00`
**Git HEAD:** `da260288b4e7320fbabe1ad5f6f234a7de6766b3`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `920` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 920 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 920 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `BTC/USD` | 92 |
| `ETH/USD` | 92 |
| `SOL/USD` | 92 |
| `AVAX/USD` | 92 |
| `LINK/USD` | 92 |
| `DOT/USD` | 92 |
| `LTC/USD` | 92 |
| `BCH/USD` | 92 |
| `UNI/USD` | 92 |
| `AAVE/USD` | 92 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 920 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 920 |

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
| Last workflow run id | `28682458074` |
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
