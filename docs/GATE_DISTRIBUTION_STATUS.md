# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-19T13:45:08.922946+00:00`
**As of:** `2026-11-19T13:45:08.640748+00:00`
**Git HEAD:** `a2bd414bff2458fe6a1535b9ac12bcf1436aaf8a`
**Window:** last 7 days
**Total ledger rows:** `18818`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 1.1% | 215/18818 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18818 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18818 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17617 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 792 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 409 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18818 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17617 |
| `crypto-oversold-bounce` | 792 |
| `crypto-breakdown` | 409 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18818 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18410 |
| `BLOCK` | 215 |
| `ALERT_ONLY` | 193 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18818 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18818 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18410 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
