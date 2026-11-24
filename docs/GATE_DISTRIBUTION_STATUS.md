# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-24T15:08:36.238046+00:00`
**As of:** `2026-11-24T15:08:35.957313+00:00`
**Git HEAD:** `a7dc4c3ee559c9184d2d8aff3aa99fda5a22e952`
**Window:** last 7 days
**Total ledger rows:** `18811`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.6% | 107/18811 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18811 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18811 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18347 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 262 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 202 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18811 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18347 |
| `crypto-oversold-bounce` | 262 |
| `crypto-breakdown` | 202 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18811 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18680 |
| `BLOCK` | 107 |
| `ALERT_ONLY` | 24 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18811 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18811 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18680 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
