# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-08T11:28:14.411037+00:00`
**As of:** `2026-11-08T11:28:14.151602+00:00`
**Git HEAD:** `59e06bd1939e6227339d425079e7f32d9488c896`
**Window:** last 7 days
**Total ledger rows:** `18450`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 85/18450 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18450 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18450 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18132 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 250 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 68 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18450 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18132 |
| `crypto-oversold-bounce` | 250 |
| `crypto-breakdown` | 68 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18450 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18307 |
| `BLOCK` | 85 |
| `ALERT_ONLY` | 58 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18450 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18450 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18307 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
