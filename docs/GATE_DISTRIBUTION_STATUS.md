# Gate Distribution Status (v3.24.0)

**Generated:** `2026-06-17T09:18:38.550936+00:00`
**As of:** `2026-06-17T09:18:38.353055+00:00`
**Git HEAD:** `1a0461ac0edb43b3a43a119e8b4f5776516f74c2`
**Window:** last 7 days
**Total ledger rows:** `15766`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=NULL` | 75.3% | confidence_score is NULL — emit path did not run, monitor missed back-fill, or downstream consumer did not persist the field. |
| `risk_decision=REJECT` | 51.9% | 8188/15766 rows blocked at the risk gate (REJECT) |
| `risk_decision=HALTED_BY_DRAWDOWN_GUARD` | 0.0% | 1/15766 rows blocked at the risk gate (HALTED_BY_DRAWDOWN_GUARD) |
| `risk_decision=NO_SIGNAL` | 22.1% | 3492/15766 rows blocked at the risk gate (NO_SIGNAL) |
| `confidence_decision=BLOCK` | 0.0% | 4/15766 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `predator_bracket` | 8042 |
| `NO_BLOCKER` | 4085 |
| `no_setup` | 3492 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `predator_bracket` | 8042 | 51.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `predator_bracket` | 8042 | 51.5% |
| `crypto-breakdown` | `short_disabled` | 86 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 47 | 67.1% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 15766 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 15610 |
| `crypto-breakdown` | 86 |
| `crypto-oversold-bounce` | 70 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `REJECT` | 8188 |
| `UNKNOWN` | 4024 |
| `NO_SIGNAL` | 3492 |
| `DETECTED` | 61 |
| `HALTED_BY_DRAWDOWN_GUARD` | 1 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `NULL` | 11874 |
| `OBSERVE_ONLY_SKIP` | 3880 |
| `ALERT_ONLY` | 8 |
| `BLOCK` | 4 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `predator_bracket` | 8042 |
| `NO_BLOCKER` | 4085 |
| `no_setup` | 3492 |
| `short_disabled` | 86 |
| `alt_cap` | 37 |
| `alpaca_reject_or_deferred` | 23 |
| `drawdown_halt` | 1 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 15705 |
| `conf_null` | 61 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P1` | 61 APPROVE/DETECTED rows lack numeric confidence_score. Wire post-decision confidence back-fill so eligible rows can accumulate. |
| `P2` | 3880 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |
| `P3` | 8188/15766 rows REJECTed. Check top blocker per strategy — fix data-quality or filter criteria, NOT risk thresholds. |
| `INFO` | 1 rows halted by drawdown guard (expected protective behaviour). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
