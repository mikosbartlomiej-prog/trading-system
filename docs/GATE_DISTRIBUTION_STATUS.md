# Gate Distribution Status (v3.24.0)

**Generated:** `2026-06-20T08:02:32.408195+00:00`
**As of:** `2026-06-20T08:02:32.195417+00:00`
**Git HEAD:** `f742d0fa5ced85a4ae521a1d921d66a6b1134c00`
**Window:** last 7 days
**Total ledger rows:** `15667`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=NULL` | 19.8% | confidence_score is NULL — emit path did not run, monitor missed back-fill, or downstream consumer did not persist the field. |
| `risk_decision=REJECT` | 13.1% | 2047/15667 rows blocked at the risk gate (REJECT) |
| `risk_decision=HALTED_BY_DRAWDOWN_GUARD` | 0.0% | 1/15667 rows blocked at the risk gate (HALTED_BY_DRAWDOWN_GUARD) |
| `risk_decision=NO_SIGNAL` | 5.8% | 903/15667 rows blocked at the risk gate (NO_SIGNAL) |
| `confidence_decision=BLOCK` | 0.1% | 23/15667 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 12716 |
| `predator_bracket` | 2023 |
| `no_setup` | 903 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 12716 | 81.2% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 12574 | 81.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 118 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 24 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 15667 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 15525 |
| `crypto-oversold-bounce` | 118 |
| `crypto-breakdown` | 24 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 12691 |
| `REJECT` | 2047 |
| `NO_SIGNAL` | 903 |
| `DETECTED` | 25 |
| `HALTED_BY_DRAWDOWN_GUARD` | 1 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 12500 |
| `NULL` | 3108 |
| `ALERT_ONLY` | 36 |
| `BLOCK` | 23 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 12716 |
| `predator_bracket` | 2023 |
| `no_setup` | 903 |
| `alt_cap` | 12 |
| `alpaca_reject_or_deferred` | 12 |
| `drawdown_halt` | 1 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 15642 |
| `conf_null` | 25 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P1` | 25 APPROVE/DETECTED rows lack numeric confidence_score. Wire post-decision confidence back-fill so eligible rows can accumulate. |
| `P2` | 12500 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |
| `INFO` | 1 rows halted by drawdown guard (expected protective behaviour). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
