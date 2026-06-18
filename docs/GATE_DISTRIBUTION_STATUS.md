# Gate Distribution Status (v3.24.0)

**Generated:** `2026-06-18T09:00:52.919092+00:00`
**As of:** `2026-06-18T09:00:52.688405+00:00`
**Git HEAD:** `e9545b98a138e72e7525cac3b5a48e392b179e91`
**Window:** last 7 days
**Total ledger rows:** `15810`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=NULL` | 56.9% | confidence_score is NULL — emit path did not run, monitor missed back-fill, or downstream consumer did not persist the field. |
| `risk_decision=REJECT` | 40.0% | 6326/15810 rows blocked at the risk gate (REJECT) |
| `risk_decision=HALTED_BY_DRAWDOWN_GUARD` | 0.0% | 1/15810 rows blocked at the risk gate (HALTED_BY_DRAWDOWN_GUARD) |
| `risk_decision=NO_SIGNAL` | 15.8% | 2494/15810 rows blocked at the risk gate (NO_SIGNAL) |
| `confidence_decision=BLOCK` | 0.1% | 12/15810 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 6989 |
| `predator_bracket` | 6204 |
| `no_setup` | 2494 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 6989 | 44.2% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 6858 | 44.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 107 | 90.7% |
| `crypto-breakdown` | `short_disabled` | 74 | 75.5% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 15810 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 15594 |
| `crypto-oversold-bounce` | 118 |
| `crypto-breakdown` | 98 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 6940 |
| `REJECT` | 6326 |
| `NO_SIGNAL` | 2494 |
| `DETECTED` | 49 |
| `HALTED_BY_DRAWDOWN_GUARD` | 1 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `NULL` | 9002 |
| `OBSERVE_ONLY_SKIP` | 6760 |
| `ALERT_ONLY` | 36 |
| `BLOCK` | 12 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 6989 |
| `predator_bracket` | 6204 |
| `no_setup` | 2494 |
| `short_disabled` | 74 |
| `alt_cap` | 25 |
| `alpaca_reject_or_deferred` | 23 |
| `drawdown_halt` | 1 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 15761 |
| `conf_null` | 49 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P1` | 49 APPROVE/DETECTED rows lack numeric confidence_score. Wire post-decision confidence back-fill so eligible rows can accumulate. |
| `P2` | 6760 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |
| `INFO` | 1 rows halted by drawdown guard (expected protective behaviour). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
