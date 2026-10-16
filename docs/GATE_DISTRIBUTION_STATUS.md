# Gate Distribution Status (v3.24.0)

**Generated:** `2026-10-16T09:12:50.087686+00:00`
**As of:** `2026-10-16T09:12:49.854370+00:00`
**Git HEAD:** `c84de2102abae94c6f523de1af1f17bd18457761`
**Window:** last 7 days
**Total ledger rows:** `18318`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 90/18318 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18318 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18318 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17390 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 472 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 456 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18318 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17390 |
| `crypto-breakdown` | 472 |
| `crypto-oversold-bounce` | 456 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18318 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18090 |
| `ALERT_ONLY` | 138 |
| `BLOCK` | 90 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18318 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18318 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18090 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
