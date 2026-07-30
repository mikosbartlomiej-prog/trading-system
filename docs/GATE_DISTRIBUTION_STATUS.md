# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-30T07:12:49.539173+00:00`
**As of:** `2026-07-30T07:12:49.317682+00:00`
**Git HEAD:** `c423fe0c18cdc51b2f897abaf7abe10d6f71a5ee`
**Window:** last 7 days
**Total ledger rows:** `18670`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 87/18670 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18670 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18670 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18296 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 276 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 98 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18670 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18296 |
| `crypto-oversold-bounce` | 276 |
| `crypto-breakdown` | 98 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18670 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18520 |
| `BLOCK` | 87 |
| `ALERT_ONLY` | 63 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18670 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18670 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18520 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
