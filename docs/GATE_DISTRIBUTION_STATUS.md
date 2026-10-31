# Gate Distribution Status (v3.24.0)

**Generated:** `2026-10-31T10:32:12.477948+00:00`
**As of:** `2026-10-31T10:32:12.202158+00:00`
**Git HEAD:** `b3234542aba06dde14d0e24711eb825bcdccaa5a`
**Window:** last 7 days
**Total ledger rows:** `18452`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 100/18452 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18452 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18452 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17874 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 438 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 140 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18452 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17874 |
| `crypto-oversold-bounce` | 438 |
| `crypto-breakdown` | 140 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18452 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18210 |
| `ALERT_ONLY` | 142 |
| `BLOCK` | 100 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18452 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18452 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18210 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
