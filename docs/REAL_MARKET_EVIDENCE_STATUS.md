# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-11-02T12:47:00.841469+00:00`
**As of:** `2026-11-02T12:47:00.766833+00:00`
**Git HEAD:** `a83878a2a5a5051818490268bcfb7a66304a1f8f`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1504` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1504 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 1436 |
| `crypto-oversold-bounce` | 68 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `AAVE/USD` | 169 |
| `UNI/USD` | 159 |
| `BTC/USD` | 147 |
| `ETH/USD` | 147 |
| `SOL/USD` | 147 |
| `AVAX/USD` | 147 |
| `LINK/USD` | 147 |
| `DOT/USD` | 147 |
| `LTC/USD` | 147 |
| `BCH/USD` | 147 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 22 |
| `0.5-0.65` | 12 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1470 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1504 |

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
| Last workflow run id | `41142499762` |
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
