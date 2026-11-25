# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-25T14:48:30.172649+00:00`
**As of:** `2026-11-25T14:48:29.934817+00:00`
**Git HEAD:** `20959f95879b6ce17009ea630edbd6acaceb9ce8`
**Window:** last 7 days
**Total ledger rows:** `18795`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.7% | 131/18795 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18795 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18795 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18307 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 286 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 202 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18795 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18307 |
| `crypto-oversold-bounce` | 286 |
| `crypto-breakdown` | 202 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18795 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18640 |
| `BLOCK` | 131 |
| `ALERT_ONLY` | 24 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18795 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18795 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18640 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
