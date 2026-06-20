# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-06-20T08:02:32.074714+00:00`
**As of:** `2026-06-20T08:02:32.006579+00:00`
**Git HEAD:** `f742d0fa5ced85a4ae521a1d921d66a6b1134c00`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `980` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 980 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 980 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `BTC/USD` | 98 |
| `ETH/USD` | 98 |
| `SOL/USD` | 98 |
| `AVAX/USD` | 98 |
| `LINK/USD` | 98 |
| `DOT/USD` | 98 |
| `LTC/USD` | 98 |
| `BCH/USD` | 98 |
| `UNI/USD` | 98 |
| `AAVE/USD` | 98 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 980 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 980 |

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
