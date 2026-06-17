# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-06-17T09:18:38.236750+00:00`
**As of:** `2026-06-17T09:18:38.194126+00:00`
**Git HEAD:** `1a0461ac0edb43b3a43a119e8b4f5776516f74c2`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1132` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1132 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 1108 |
| `crypto-oversold-bounce` | 24 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `SOL/USD` | 116 |
| `LINK/USD` | 116 |
| `BCH/USD` | 116 |
| `BTC/USD` | 112 |
| `ETH/USD` | 112 |
| `AVAX/USD` | 112 |
| `DOT/USD` | 112 |
| `LTC/USD` | 112 |
| `UNI/USD` | 112 |
| `AAVE/USD` | 112 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 4 |
| `0.5-0.65` | 8 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1120 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1132 |

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
| Last workflow run id | `27649420427` |
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
