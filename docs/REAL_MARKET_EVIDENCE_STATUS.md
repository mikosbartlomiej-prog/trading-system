# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-06-26T08:07:31.187211+00:00`
**As of:** `2026-06-26T08:07:31.116972+00:00`
**Git HEAD:** `3bfaffb9279abc66f3685f44a2c01c6f27810afe`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1026` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1026 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-breakdown` | 97 |
| `crypto-momentum` | 877 |
| `crypto-oversold-bounce` | 52 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `ETH/USD` | 113 |
| `LINK/USD` | 113 |
| `BTC/USD` | 100 |
| `SOL/USD` | 100 |
| `AVAX/USD` | 100 |
| `DOT/USD` | 100 |
| `LTC/USD` | 100 |
| `BCH/USD` | 100 |
| `UNI/USD` | 100 |
| `AAVE/USD` | 100 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 13 |
| `0.5-0.65` | 13 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1000 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1026 |

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
| Last workflow run id | `28198764506` |
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
