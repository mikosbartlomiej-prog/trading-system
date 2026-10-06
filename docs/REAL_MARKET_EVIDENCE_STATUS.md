# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-10-06T11:26:17.263224+00:00`
**As of:** `2026-10-06T11:26:17.212379+00:00`
**Git HEAD:** `294759eaf5f78f4f2e4cb03347dc53aecd7dfbe8`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1373` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1373 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-breakdown` | 12 |
| `crypto-momentum` | 1315 |
| `crypto-oversold-bounce` | 46 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `DOT/USD` | 147 |
| `BTC/USD` | 146 |
| `ETH/USD` | 135 |
| `SOL/USD` | 135 |
| `AVAX/USD` | 135 |
| `LINK/USD` | 135 |
| `LTC/USD` | 135 |
| `BCH/USD` | 135 |
| `UNI/USD` | 135 |
| `AAVE/USD` | 135 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 12 |
| `0.5-0.65` | 11 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1350 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1373 |

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
| Last workflow run id | `37076303669` |
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
