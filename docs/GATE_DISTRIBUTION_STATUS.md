# Gate Distribution Status (v3.24.0)

**Generated:** `2026-09-01T09:32:58.944834+00:00`
**As of:** `2026-09-01T09:32:58.700316+00:00`
**Git HEAD:** `86745c47915b7fffc392e9bb88c7d2231e936dd1`
**Window:** last 7 days
**Total ledger rows:** `18363`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.4% | 73/18363 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18363 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18363 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18139 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 120 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 104 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18363 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18139 |
| `crypto-oversold-bounce` | 120 |
| `crypto-breakdown` | 104 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18363 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18280 |
| `BLOCK` | 73 |
| `ALERT_ONLY` | 10 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18363 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18363 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18280 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
