# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-20T13:27:28.796488+00:00`
**As of:** `2026-11-20T13:27:28.624922+00:00`
**Git HEAD:** `c9a19b634b3dc95b075f62a0ed9d705e5d53f63d`
**Window:** last 7 days
**Total ledger rows:** `18751`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 1.0% | 180/18751 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18751 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18751 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17697 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 678 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 376 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18751 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17697 |
| `crypto-oversold-bounce` | 678 |
| `crypto-breakdown` | 376 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18751 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18400 |
| `BLOCK` | 180 |
| `ALERT_ONLY` | 171 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18751 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18751 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18400 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
