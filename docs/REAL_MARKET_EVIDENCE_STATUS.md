# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-08-01T07:02:35.066407+00:00`
**As of:** `2026-08-01T07:02:34.998786+00:00`
**Git HEAD:** `da36e25c38c1b56a8761c1937d5c75bd59344ffa`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `871` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 871 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 871 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `UNI/USD` | 88 |
| `BTC/USD` | 87 |
| `ETH/USD` | 87 |
| `SOL/USD` | 87 |
| `AVAX/USD` | 87 |
| `LINK/USD` | 87 |
| `DOT/USD` | 87 |
| `LTC/USD` | 87 |
| `BCH/USD` | 87 |
| `AAVE/USD` | 87 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 1 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 870 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 871 |

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
| Last workflow run id | `30661472232` |
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
