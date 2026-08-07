# Gate Distribution Status (v3.24.0)

**Generated:** `2026-08-07T05:56:13.749569+00:00`
**As of:** `2026-08-07T05:56:13.493748+00:00`
**Git HEAD:** `f9c9187a5108183a98115aef47b26945c975334b`
**Window:** last 7 days
**Total ledger rows:** `17746`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 87/17746 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 17746 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 17746 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17284 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 378 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 84 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 17746 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17284 |
| `crypto-oversold-bounce` | 378 |
| `crypto-breakdown` | 84 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 17746 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 17538 |
| `ALERT_ONLY` | 121 |
| `BLOCK` | 87 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 17746 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 17746 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 17538 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
