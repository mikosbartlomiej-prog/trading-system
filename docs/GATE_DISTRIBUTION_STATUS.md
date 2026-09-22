# Gate Distribution Status (v3.24.0)

**Generated:** `2026-09-22T09:26:14.818466+00:00`
**As of:** `2026-09-22T09:26:14.580046+00:00`
**Git HEAD:** `05c1e73448a817d500e2620ded8a79b8152199b0`
**Window:** last 7 days
**Total ledger rows:** `18567`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 91/18567 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18567 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18567 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18240 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 244 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 83 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18567 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18240 |
| `crypto-oversold-bounce` | 244 |
| `crypto-breakdown` | 83 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18567 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18420 |
| `BLOCK` | 91 |
| `ALERT_ONLY` | 56 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18567 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18567 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18420 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
