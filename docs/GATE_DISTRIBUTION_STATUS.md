# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-26T14:13:47.391643+00:00`
**As of:** `2026-11-26T14:13:47.084469+00:00`
**Git HEAD:** `2c69dfe7208dbac8376e95c09ff196ffd4e0cbf0`
**Window:** last 7 days
**Total ledger rows:** `18637`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.8% | 143/18637 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18637 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18637 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18149 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 286 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 202 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18637 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18149 |
| `crypto-oversold-bounce` | 286 |
| `crypto-breakdown` | 202 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18637 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18470 |
| `BLOCK` | 143 |
| `ALERT_ONLY` | 24 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18637 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18637 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18470 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
