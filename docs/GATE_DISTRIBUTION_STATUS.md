# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-27T08:01:40.066628+00:00`
**As of:** `2026-07-27T08:01:39.805579+00:00`
**Git HEAD:** `339e051d3e306195a975275a9d874d7946ee41dc`
**Window:** last 7 days
**Total ledger rows:** `18677`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.6% | 111/18677 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18677 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18677 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18388 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 250 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 39 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18677 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18388 |
| `crypto-oversold-bounce` | 250 |
| `crypto-breakdown` | 39 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18677 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18540 |
| `BLOCK` | 111 |
| `ALERT_ONLY` | 26 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18677 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18677 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18540 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
