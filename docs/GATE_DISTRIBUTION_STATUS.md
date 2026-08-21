# Gate Distribution Status (v3.24.0)

**Generated:** `2026-08-21T05:05:08.965059+00:00`
**As of:** `2026-08-21T05:05:08.773003+00:00`
**Git HEAD:** `d8182569010b84ec584e4948481fc21de33b3dd6`
**Window:** last 7 days
**Total ledger rows:** `20068`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.8% | 151/20068 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 20068 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 20068 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 19642 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 376 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 50 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 20068 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 19642 |
| `crypto-oversold-bounce` | 376 |
| `crypto-breakdown` | 50 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 20068 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 19880 |
| `BLOCK` | 151 |
| `ALERT_ONLY` | 37 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 20068 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 20068 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 19880 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
