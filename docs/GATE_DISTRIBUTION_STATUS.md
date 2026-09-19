# Gate Distribution Status (v3.24.0)

**Generated:** `2026-09-19T08:54:21.971057+00:00`
**As of:** `2026-09-19T08:54:21.798380+00:00`
**Git HEAD:** `36f747e51e48b90841ac9f8d6af3e77334ab45b1`
**Window:** last 7 days
**Total ledger rows:** `18491`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 88/18491 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18491 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18491 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18046 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 362 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 83 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18491 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18046 |
| `crypto-oversold-bounce` | 362 |
| `crypto-breakdown` | 83 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18491 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18310 |
| `ALERT_ONLY` | 93 |
| `BLOCK` | 88 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18491 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18491 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18310 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
