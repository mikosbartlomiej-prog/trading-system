# Real-Market Evidence Status (v3.23.0)

**Generated:** `2026-11-12T13:06:31.631915+00:00`
**As of:** `2026-11-12T13:06:31.546036+00:00`
**Git HEAD:** `f88c64c1d2236334d574228c715870ba9d66f948`
**Current blocker:** **`NO_REAL_MARKET_DATA`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `1531` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `0` |
| Observation records today (DO NOT count toward unlock) | `0` |

## By monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 1531 |

## By strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 1509 |
| `crypto-oversold-bounce` | 22 |

## By symbol (top 10)

| Symbol | Count |
|---|---|
| `ETH/USD` | 163 |
| `BTC/USD` | 152 |
| `SOL/USD` | 152 |
| `AVAX/USD` | 152 |
| `LINK/USD` | 152 |
| `DOT/USD` | 152 |
| `LTC/USD` | 152 |
| `BCH/USD` | 152 |
| `UNI/USD` | 152 |
| `AAVE/USD` | 152 |

## Confidence-score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 3 |
| `0.5-0.65` | 8 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 1520 |

## Gate-decision distribution

| Decision | Count |
|---|---|
| `UNKNOWN` | 1531 |

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
| Last workflow run id | `42896451891` |
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
