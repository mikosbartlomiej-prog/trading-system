# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-01T08:35:48.030246+00:00`
**As of:** `2026-07-01T08:35:47.743548+00:00`
**Git HEAD:** `f5d3e51ab0d8827da688523be7a8bc21f5f4a3be`
**Window:** last 7 days
**Total ledger rows:** `18991`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 1.0% | 196/18991 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18991 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18991 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18029 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 586 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 376 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18991 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18029 |
| `crypto-oversold-bounce` | 586 |
| `crypto-breakdown` | 376 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18991 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18686 |
| `BLOCK` | 196 |
| `ALERT_ONLY` | 109 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18991 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18991 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18686 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
