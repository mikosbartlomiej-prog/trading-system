# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-11-10T12:53:46.943517+00:00`
**As of:** `2026-11-10T12:53:46.876727+00:00`
**Git HEAD:** `cb9ddec0b656ff24f8b3a74e11ea4e28abdceca2`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1542` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1542 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 1518 |
| `crypto-oversold-bounce` | 24 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `DOT/USD` | 165 |
| `BTC/USD` | 153 |
| `ETH/USD` | 153 |
| `SOL/USD` | 153 |
| `AVAX/USD` | 153 |
| `LINK/USD` | 153 |
| `LTC/USD` | 153 |
| `BCH/USD` | 153 |
| `UNI/USD` | 153 |
| `AAVE/USD` | 153 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 12 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1530 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1542 |

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
| Last workflow run id | `42717663042` |
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
