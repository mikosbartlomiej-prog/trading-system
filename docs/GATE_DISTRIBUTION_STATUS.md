# Gate Distribution Status (v3.24.0)

**Generated:** `2026-06-19T09:19:36.610843+00:00`
**As of:** `2026-06-19T09:19:36.418718+00:00`
**Git HEAD:** `56533d2e160ff0d5e2fa5e3698168d86e83b7eb7`
**Window:** last 7 days
**Total ledger rows:** `15850`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=NULL` | 38.4% | confidence_score is NULL — emit path did not run, monitor missed back-fill, or downstream consumer did not persist the field. |
| `risk_decision=REJECT` | 25.5% | 4046/15850 rows blocked at the risk gate (REJECT) |
| `risk_decision=HALTED_BY_DRAWDOWN_GUARD` | 0.0% | 1/15850 rows blocked at the risk gate (HALTED_BY_DRAWDOWN_GUARD) |
| `risk_decision=NO_SIGNAL` | 11.8% | 1874/15850 rows blocked at the risk gate (NO_SIGNAL) |
| `confidence_decision=BLOCK` | 0.1% | 23/15850 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 9929 |
| `predator_bracket` | 3983 |
| `no_setup` | 1874 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 9929 | 62.6% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 9787 | 62.4% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 118 | 100.0% |
| `crypto-breakdown` | `short_disabled` | 26 | 52.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 15850 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 15682 |
| `crypto-oversold-bounce` | 118 |
| `crypto-breakdown` | 50 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 9891 |
| `REJECT` | 4046 |
| `NO_SIGNAL` | 1874 |
| `DETECTED` | 38 |
| `HALTED_BY_DRAWDOWN_GUARD` | 1 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 9700 |
| `NULL` | 6091 |
| `ALERT_ONLY` | 36 |
| `BLOCK` | 23 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 9929 |
| `predator_bracket` | 3983 |
| `no_setup` | 1874 |
| `short_disabled` | 26 |
| `alt_cap` | 25 |
| `alpaca_reject_or_deferred` | 12 |
| `drawdown_halt` | 1 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 15812 |
| `conf_null` | 38 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P1` | 38 APPROVE/DETECTED rows lack numeric confidence_score. Wire post-decision confidence back-fill so eligible rows can accumulate. |
| `P2` | 9700 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |
| `INFO` | 1 rows halted by drawdown guard (expected protective behaviour). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
