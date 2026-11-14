# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-14T11:41:43.800962+00:00`
**As of:** `2026-11-14T11:41:43.546550+00:00`
**Git HEAD:** `59549b9148b29d877dbd035fefd07dcb2c36b578`
**Window:** last 7 days
**Total ledger rows:** `18482`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.7% | 122/18482 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18482 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18482 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17820 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 444 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 218 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18482 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17820 |
| `crypto-oversold-bounce` | 444 |
| `crypto-breakdown` | 218 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18482 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18260 |
| `BLOCK` | 122 |
| `ALERT_ONLY` | 100 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18482 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18482 |

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
