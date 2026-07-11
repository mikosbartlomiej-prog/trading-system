# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-11T06:35:39.411928+00:00`
**As of:** `2026-07-11T06:35:39.160595+00:00`
**Git HEAD:** `bee645ed13690140ef1600b75601d994542678e5`
**Window:** last 7 days
**Total ledger rows:** `18337`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.7% | 135/18337 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18337 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18337 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17979 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 292 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 66 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18337 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17979 |
| `crypto-oversold-bounce` | 292 |
| `crypto-breakdown` | 66 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18337 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18140 |
| `BLOCK` | 135 |
| `ALERT_ONLY` | 62 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18337 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18337 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18140 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
