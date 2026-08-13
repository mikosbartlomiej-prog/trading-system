# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-08-13T05:57:23.567039+00:00`
**As of:** `2026-08-13T05:57:23.493691+00:00`
**Git HEAD:** `4be67a1a6357e7c6896524cbe1a5ec8dfd886908`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `743` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 743 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 697 |
| `crypto-oversold-bounce` | 46 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `LTC/USD` | 95 |
| `BTC/USD` | 72 |
| `ETH/USD` | 72 |
| `SOL/USD` | 72 |
| `AVAX/USD` | 72 |
| `LINK/USD` | 72 |
| `DOT/USD` | 72 |
| `BCH/USD` | 72 |
| `UNI/USD` | 72 |
| `AAVE/USD` | 72 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 23 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 720 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 743 |

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
| Last workflow run id | `31633718231` |
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
