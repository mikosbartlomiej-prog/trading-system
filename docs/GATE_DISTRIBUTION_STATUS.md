# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-16T06:43:02.525776+00:00`
**As of:** `2026-07-16T06:43:02.246395+00:00`
**Git HEAD:** `d367c1756495dd550c381db72fd7a13091d567f2`
**Window:** last 7 days
**Total ledger rows:** `18855`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.6% | 114/18855 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18855 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18855 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18366 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 350 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 139 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18855 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18366 |
| `crypto-oversold-bounce` | 350 |
| `crypto-breakdown` | 139 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18855 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18680 |
| `BLOCK` | 114 |
| `ALERT_ONLY` | 61 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18855 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18855 |

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
