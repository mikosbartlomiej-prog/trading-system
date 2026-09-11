# Gate Distribution Status (v3.24.0)

**Generated:** `2026-09-11T09:02:28.642023+00:00`
**As of:** `2026-09-11T09:02:28.286571+00:00`
**Git HEAD:** `fb1d5ab6a30d8d48428f5f5a9f8753d64d571641`
**Window:** last 7 days
**Total ledger rows:** `17766`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.2% | 33/17766 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 17766 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 17766 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17716 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 50 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 17766 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17716 |
| `crypto-oversold-bounce` | 50 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 17766 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 17720 |
| `BLOCK` | 33 |
| `ALERT_ONLY` | 13 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 17766 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 17766 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 17720 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
