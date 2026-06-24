# Gate Distribution Status (v3.24.0)

**Generated:** `2026-06-24T07:58:54.886384+00:00`
**As of:** `2026-06-24T07:58:54.626363+00:00`
**Git HEAD:** `0c52c40f416ba7ed79215add5d635d4a3080faf3`
**Window:** last 7 days
**Total ledger rows:** `18657`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.3% | 61/18657 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18657 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18657 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18367 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 194 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 96 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18657 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18367 |
| `crypto-oversold-bounce` | 194 |
| `crypto-breakdown` | 96 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18657 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18536 |
| `BLOCK` | 61 |
| `ALERT_ONLY` | 60 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18657 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18657 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18536 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
