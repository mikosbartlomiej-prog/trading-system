# Gate Distribution Status (v3.24.0)

**Generated:** `2026-08-03T07:56:59.784575+00:00`
**As of:** `2026-08-03T07:56:59.527375+00:00`
**Git HEAD:** `9b18025fc7e3b82f54ee9f5783a537861542f478`
**Window:** last 7 days
**Total ledger rows:** `18857`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 88/18857 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18857 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18857 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18506 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 248 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 103 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18857 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18506 |
| `crypto-oversold-bounce` | 248 |
| `crypto-breakdown` | 103 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18857 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18720 |
| `BLOCK` | 88 |
| `ALERT_ONLY` | 49 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18857 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18857 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18720 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
