# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-06-15T11:28:34.393719+00:00`
**As of:** `2026-06-15T11:28:34.352268+00:00`
**Git HEAD:** `a8186d5f70f66f77b86d337f936541bea06c544b`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `134` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `7` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 134 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 134 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `BTC/USD` | 17 |
| `ETH/USD` | 13 |
| `SOL/USD` | 13 |
| `AVAX/USD` | 13 |
| `LINK/USD` | 13 |
| `DOT/USD` | 13 |
| `LTC/USD` | 13 |
| `BCH/USD` | 13 |
| `UNI/USD` | 13 |
| `AAVE/USD` | 13 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 134 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `DETECTED` | 1 |
| `HALTED_BY_DRAWDOWN_GUARD` | 1 |
| `UNKNOWN` | 132 |

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
| Last workflow run id | `27441653073` |
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
