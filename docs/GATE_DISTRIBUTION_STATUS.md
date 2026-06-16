# Gate Distribution Status (v3.24.0)

**Generated:** `2026-06-16T09:40:02.071925+00:00`
**As of:** `2026-06-16T09:40:01.872183+00:00`
**Git HEAD:** `5d493ee95ba682d032a8c55b16cb9b0f321c2280`
**Window:** last 7 days
**Total ledger rows:** `16128`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=NULL` | 90.9% | confidence_score is NULL — emit path did not run, monitor missed back-fill, or downstream consumer did not persist the field. |
| `risk_decision=REJECT` | 59.0% | 9517/16128 rows blocked at the risk gate (REJECT) |
| `risk_decision=HALTED_BY_DRAWDOWN_GUARD` | 0.0% | 1/16128 rows blocked at the risk gate (HALTED_BY_DRAWDOWN_GUARD) |
| `risk_decision=NO_SIGNAL` | 30.5% | 4923/16128 rows blocked at the risk gate (NO_SIGNAL) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `predator_bracket` | 9347 |
| `no_setup` | 4923 |
| `NO_BLOCKER` | 1687 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `predator_bracket` | 9347 | 58.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `predator_bracket` | 9347 | 58.4% |
| `crypto-breakdown` | `short_disabled` | 86 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 23 | 50.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 16128 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 15996 |
| `crypto-breakdown` | 86 |
| `crypto-oversold-bounce` | 46 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `REJECT` | 9517 |
| `NO_SIGNAL` | 4923 |
| `UNKNOWN` | 1602 |
| `DETECTED` | 85 |
| `HALTED_BY_DRAWDOWN_GUARD` | 1 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `NULL` | 14658 |
| `OBSERVE_ONLY_SKIP` | 1470 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `predator_bracket` | 9347 |
| `no_setup` | 4923 |
| `NO_BLOCKER` | 1687 |
| `short_disabled` | 86 |
| `alt_cap` | 49 |
| `alpaca_reject_or_deferred` | 35 |
| `drawdown_halt` | 1 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 16043 |
| `conf_null` | 85 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P1` | 85 APPROVE/DETECTED rows lack numeric confidence_score. Wire post-decision confidence back-fill so eligible rows can accumulate. |
| `P2` | 1470 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |
| `P3` | 9517/16128 rows REJECTed. Check top blocker per strategy — fix data-quality or filter criteria, NOT risk thresholds. |
| `INFO` | 1 rows halted by drawdown guard (expected protective behaviour). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
