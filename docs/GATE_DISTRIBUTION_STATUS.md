# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-24T07:07:22.976186+00:00`
**As of:** `2026-07-24T07:07:22.754611+00:00`
**Git HEAD:** `2bf5953027a638e186a309dbed5f386289d4d1e7`
**Window:** last 7 days
**Total ledger rows:** `14363`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 68/14363 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 14363 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 14363 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 14212 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 142 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 9 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 14363 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 14212 |
| `crypto-oversold-bounce` | 142 |
| `crypto-breakdown` | 9 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 14363 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 14280 |
| `BLOCK` | 68 |
| `ALERT_ONLY` | 15 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 14363 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 14363 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 14280 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
