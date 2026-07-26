# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-26T07:10:30.314579+00:00`
**As of:** `2026-07-26T07:10:30.111980+00:00`
**Git HEAD:** `b7246656db3e5641e278dc82f536720388ded0ae`
**Window:** last 7 days
**Total ledger rows:** `15921`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 74/15921 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 15921 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 15921 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 15730 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 178 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 13 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 15921 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 15730 |
| `crypto-oversold-bounce` | 178 |
| `crypto-breakdown` | 13 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 15921 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 15820 |
| `BLOCK` | 74 |
| `ALERT_ONLY` | 27 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 15921 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 15921 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 15820 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
