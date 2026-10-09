# Gate Distribution Status (v3.24.0)

**Generated:** `2026-10-09T11:28:14.211464+00:00`
**As of:** `2026-10-09T11:28:13.945241+00:00`
**Git HEAD:** `3093858795c61b7d842621ccc3ede251f8111c49`
**Window:** last 7 days
**Total ledger rows:** `18239`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.3% | 48/18239 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18239 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18239 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18004 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 198 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 37 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18239 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18004 |
| `crypto-oversold-bounce` | 198 |
| `crypto-breakdown` | 37 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18239 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18140 |
| `ALERT_ONLY` | 51 |
| `BLOCK` | 48 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18239 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18239 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18140 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
