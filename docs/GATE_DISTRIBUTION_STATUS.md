# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-08T07:03:53.116125+00:00`
**As of:** `2026-07-08T07:03:52.841627+00:00`
**Git HEAD:** `5cf79f0fdb7bc75312b5244db7e876d5928dd08a`
**Window:** last 7 days
**Total ledger rows:** `18690`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 91/18690 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18690 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18690 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18488 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 178 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 24 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18690 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18488 |
| `crypto-oversold-bounce` | 178 |
| `crypto-breakdown` | 24 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18690 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18550 |
| `BLOCK` | 91 |
| `ALERT_ONLY` | 49 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18690 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18690 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18550 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
