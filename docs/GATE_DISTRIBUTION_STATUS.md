# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-03T12:12:50.644855+00:00`
**As of:** `2026-11-03T12:12:50.391512+00:00`
**Git HEAD:** `26598117a1b16a2a16b7268aae72d0fe8e1df2b4`
**Window:** last 7 days
**Total ledger rows:** `18553`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.8% | 143/18553 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18553 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18553 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18079 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 288 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 186 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18553 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18079 |
| `crypto-oversold-bounce` | 288 |
| `crypto-breakdown` | 186 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18553 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18386 |
| `BLOCK` | 143 |
| `ALERT_ONLY` | 24 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18553 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18553 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18386 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
