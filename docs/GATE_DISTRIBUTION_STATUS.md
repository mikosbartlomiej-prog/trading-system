# Gate Distribution Status (v3.24.0)

**Generated:** `2026-06-21T08:45:59.246058+00:00`
**As of:** `2026-06-21T08:45:59.004498+00:00`
**Git HEAD:** `c9db3d52cabdda03692add3ade468528d9862ff9`
**Window:** last 7 days
**Total ledger rows:** `15809`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=NULL` | 0.8% | confidence_score is NULL — emit path did not run, monitor missed back-fill, or downstream consumer did not persist the field. |
| `risk_decision=HALTED_BY_DRAWDOWN_GUARD` | 0.0% | 1/15809 rows blocked at the risk gate (HALTED_BY_DRAWDOWN_GUARD) |
| `confidence_decision=BLOCK` | 0.2% | 36/15809 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 15808 |
| `drawdown_halt` | 1 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 15808 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 15580 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 192 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 36 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 15809 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 15581 |
| `crypto-oversold-bounce` | 192 |
| `crypto-breakdown` | 36 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 15807 |
| `DETECTED` | 1 |
| `HALTED_BY_DRAWDOWN_GUARD` | 1 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 15579 |
| `NULL` | 134 |
| `ALERT_ONLY` | 60 |
| `BLOCK` | 36 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 15808 |
| `drawdown_halt` | 1 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 15808 |
| `conf_null` | 1 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P1` | 1 APPROVE/DETECTED rows lack numeric confidence_score. Wire post-decision confidence back-fill so eligible rows can accumulate. |
| `P2` | 15579 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |
| `INFO` | 1 rows halted by drawdown guard (expected protective behaviour). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
