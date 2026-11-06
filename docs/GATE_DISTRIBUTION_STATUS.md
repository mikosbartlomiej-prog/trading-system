# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-06T12:21:52.630919+00:00`
**As of:** `2026-11-06T12:21:52.463808+00:00`
**Git HEAD:** `e1af0d58d8c4caf39b1f23b6e234e5090fa77e56`
**Window:** last 7 days
**Total ledger rows:** `18564`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.7% | 122/18564 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18564 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18564 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17985 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 348 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 231 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18564 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17985 |
| `crypto-oversold-bounce` | 348 |
| `crypto-breakdown` | 231 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18564 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18384 |
| `BLOCK` | 122 |
| `ALERT_ONLY` | 58 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18564 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18564 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18384 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
