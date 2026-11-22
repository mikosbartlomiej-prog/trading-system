# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-22T12:47:26.719988+00:00`
**As of:** `2026-11-22T12:47:26.551360+00:00`
**Git HEAD:** `6efecfc18f3d23331121dbcfd66d41c10ed15d9f`
**Window:** last 7 days
**Total ledger rows:** `18424`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.4% | 70/18424 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18424 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18424 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17744 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 352 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 328 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18424 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17744 |
| `crypto-breakdown` | 352 |
| `crypto-oversold-bounce` | 328 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18424 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18260 |
| `ALERT_ONLY` | 94 |
| `BLOCK` | 70 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18424 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18424 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18260 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
