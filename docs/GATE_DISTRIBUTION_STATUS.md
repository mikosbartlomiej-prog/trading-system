# Gate Distribution Status (v3.24.0)

**Generated:** `2026-08-12T05:55:35.921539+00:00`
**As of:** `2026-08-12T05:55:35.666940+00:00`
**Git HEAD:** `88f932c1bd3478436844c6b222a905d75e999f90`
**Window:** last 7 days
**Total ledger rows:** `18438`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.9% | 160/18438 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18438 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18438 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17946 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 416 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 76 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18438 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17946 |
| `crypto-oversold-bounce` | 416 |
| `crypto-breakdown` | 76 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18438 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18230 |
| `BLOCK` | 160 |
| `ALERT_ONLY` | 48 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18438 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18438 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18230 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
