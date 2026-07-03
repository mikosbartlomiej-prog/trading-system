# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-07-03T07:45:50.006117+00:00`
**As of:** `2026-07-03T07:45:49.929093+00:00`
**Git HEAD:** `05143a538d8779d37e723037fd362094f07e857a`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `955` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 955 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 905 |
| `crypto-oversold-bounce` | 50 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `BTC/USD` | 106 |
| `LTC/USD` | 105 |
| `ETH/USD` | 93 |
| `SOL/USD` | 93 |
| `AVAX/USD` | 93 |
| `LINK/USD` | 93 |
| `DOT/USD` | 93 |
| `BCH/USD` | 93 |
| `UNI/USD` | 93 |
| `AAVE/USD` | 93 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 12 |
| `0.5-0.65` | 13 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 930 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 955 |

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
| Last workflow run id | `28618154013` |
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
