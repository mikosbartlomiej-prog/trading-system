# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-02T07:50:39.938149+00:00`
**As of:** `2026-07-02T07:50:39.659821+00:00`
**Git HEAD:** `f313f22b8bbc044bd8119b0b8758e4f5015ceb8a`
**Window:** last 7 days
**Total ledger rows:** `18868`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.9% | 170/18868 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18868 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18868 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17932 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 560 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 376 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18868 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17932 |
| `crypto-oversold-bounce` | 560 |
| `crypto-breakdown` | 376 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18868 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18576 |
| `BLOCK` | 170 |
| `ALERT_ONLY` | 122 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18868 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18868 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18576 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
