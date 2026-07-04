# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-07-04T07:22:16.367433+00:00`
**As of:** `2026-07-04T07:22:16.295768+00:00`
**Git HEAD:** `dfd4fb2a95f1cf52f40ea9b6b49ef4ce7ec10fb4`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `890` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 890 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 890 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `BTC/USD` | 89 |
| `ETH/USD` | 89 |
| `SOL/USD` | 89 |
| `AVAX/USD` | 89 |
| `LINK/USD` | 89 |
| `DOT/USD` | 89 |
| `LTC/USD` | 89 |
| `BCH/USD` | 89 |
| `UNI/USD` | 89 |
| `AAVE/USD` | 89 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 890 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 890 |

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
