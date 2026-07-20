# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-20T07:41:05.535248+00:00`
**As of:** `2026-07-20T07:41:05.300739+00:00`
**Git HEAD:** `f105607a56a8984ab59b7c2de813f39895c3b951`
**Window:** last 7 days
**Total ledger rows:** `16339`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 80/16339 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 16339 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 16339 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 16017 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 238 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 84 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 16339 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 16017 |
| `crypto-oversold-bounce` | 238 |
| `crypto-breakdown` | 84 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 16339 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 16220 |
| `BLOCK` | 80 |
| `ALERT_ONLY` | 39 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 16339 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 16339 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 16220 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
