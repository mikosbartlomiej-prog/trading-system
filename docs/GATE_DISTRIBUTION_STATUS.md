# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-05T07:43:44.333527+00:00`
**As of:** `2026-07-05T07:43:44.079610+00:00`
**Git HEAD:** `da260288b4e7320fbabe1ad5f6f234a7de6766b3`
**Window:** last 7 days
**Total ledger rows:** `18727`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 101/18727 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18727 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18727 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18443 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 260 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 24 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18727 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18443 |
| `crypto-oversold-bounce` | 260 |
| `crypto-breakdown` | 24 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18727 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18578 |
| `BLOCK` | 101 |
| `ALERT_ONLY` | 48 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18727 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18727 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18578 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
