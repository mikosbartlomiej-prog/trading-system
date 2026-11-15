# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-11-15T12:09:36.428888+00:00`
**As of:** `2026-11-15T12:09:36.378676+00:00`
**Git HEAD:** `799f366bd8e826bc4aa22cb399bf76a535d11bd9`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1554` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1554 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-breakdown` | 48 |
| `crypto-momentum` | 1338 |
| `crypto-oversold-bounce` | 168 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `UNI/USD` | 183 |
| `ETH/USD` | 160 |
| `BTC/USD` | 159 |
| `AAVE/USD` | 159 |
| `DOT/USD` | 158 |
| `SOL/USD` | 147 |
| `AVAX/USD` | 147 |
| `LINK/USD` | 147 |
| `LTC/USD` | 147 |
| `BCH/USD` | 147 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 60 |
| `0.5-0.65` | 24 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1470 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1554 |

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
| Last workflow run id | `43503186327` |
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
