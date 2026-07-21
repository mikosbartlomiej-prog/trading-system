# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-21T07:07:33.742112+00:00`
**As of:** `2026-07-21T07:07:33.538001+00:00`
**Git HEAD:** `df92d079c55672179d46c99b062af36b2442d73f`
**Window:** last 7 days
**Total ledger rows:** `14460`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.6% | 80/14460 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 14460 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 14460 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 14149 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 240 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 71 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 14460 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 14149 |
| `crypto-oversold-bounce` | 240 |
| `crypto-breakdown` | 71 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 14460 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 14340 |
| `BLOCK` | 80 |
| `ALERT_ONLY` | 40 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 14460 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 14460 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 14340 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
