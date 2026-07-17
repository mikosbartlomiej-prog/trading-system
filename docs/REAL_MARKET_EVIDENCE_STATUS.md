# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-07-17T06:38:14.955468+00:00`
**As of:** `2026-07-17T06:38:14.890405+00:00`
**Git HEAD:** `94ffd271b643a9b405b16dbeb223ba58d59610ba`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `830` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 830 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 830 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `BTC/USD` | 83 |
| `ETH/USD` | 83 |
| `SOL/USD` | 83 |
| `AVAX/USD` | 83 |
| `LINK/USD` | 83 |
| `DOT/USD` | 83 |
| `LTC/USD` | 83 |
| `BCH/USD` | 83 |
| `UNI/USD` | 83 |
| `AAVE/USD` | 83 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 830 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 830 |

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
| Last workflow run id | `29532210203` |
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
