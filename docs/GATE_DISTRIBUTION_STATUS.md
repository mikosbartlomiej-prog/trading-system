# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-07T11:16:01.643529+00:00`
**As of:** `2026-11-07T11:16:01.425267+00:00`
**Git HEAD:** `c0b0b5f9757f9f3319a32940158e93ab0ad1ed07`
**Window:** last 7 days
**Total ledger rows:** `18448`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.7% | 122/18448 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18448 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18448 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17906 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 324 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 218 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18448 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17906 |
| `crypto-oversold-bounce` | 324 |
| `crypto-breakdown` | 218 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18448 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18268 |
| `BLOCK` | 122 |
| `ALERT_ONLY` | 58 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18448 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18448 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18268 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
