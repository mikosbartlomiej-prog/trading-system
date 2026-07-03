# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-03T07:45:50.567102+00:00`
**As of:** `2026-07-03T07:45:50.272960+00:00`
**Git HEAD:** `05143a538d8779d37e723037fd362094f07e857a`
**Window:** last 7 days
**Total ledger rows:** `18725`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 86/18725 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18725 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18725 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18215 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 256 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 254 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18725 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18215 |
| `crypto-oversold-bounce` | 256 |
| `crypto-breakdown` | 254 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18725 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18578 |
| `BLOCK` | 86 |
| `ALERT_ONLY` | 61 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18725 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18725 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18578 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
