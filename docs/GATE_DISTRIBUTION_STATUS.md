# Gate Distribution Status (v3.24.0)

**Generated:** `2026-08-16T05:01:21.674841+00:00`
**As of:** `2026-08-16T05:01:21.366636+00:00`
**Git HEAD:** `f531d2232b7603b945fa46164e2c206d083a5653`
**Window:** last 7 days
**Total ledger rows:** `19155`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.8% | 151/19155 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 19155 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 19155 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18585 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 482 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 88 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 19155 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18585 |
| `crypto-oversold-bounce` | 482 |
| `crypto-breakdown` | 88 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 19155 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18908 |
| `BLOCK` | 151 |
| `ALERT_ONLY` | 96 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 19155 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 19155 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18908 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
