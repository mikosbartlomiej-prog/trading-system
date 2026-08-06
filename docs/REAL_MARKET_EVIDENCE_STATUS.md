# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-08-06T07:15:56.859728+00:00`
**As of:** `2026-08-06T07:15:56.788529+00:00`
**Git HEAD:** `717b0a1e883e455077187d6e4385ad43ce1d72cd`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `844` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 844 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-breakdown` | 10 |
| `crypto-momentum` | 826 |
| `crypto-oversold-bounce` | 8 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `AVAX/USD` | 88 |
| `BTC/USD` | 84 |
| `ETH/USD` | 84 |
| `SOL/USD` | 84 |
| `LINK/USD` | 84 |
| `DOT/USD` | 84 |
| `LTC/USD` | 84 |
| `BCH/USD` | 84 |
| `UNI/USD` | 84 |
| `AAVE/USD` | 84 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 4 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 840 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 844 |

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
| Last workflow run id | `31042804050` |
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
