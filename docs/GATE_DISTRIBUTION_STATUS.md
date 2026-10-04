# Gate Distribution Status (v3.24.0)

**Generated:** `2026-10-04T10:42:56.478077+00:00`
**As of:** `2026-10-04T10:42:56.255404+00:00`
**Git HEAD:** `1960123b0d042c33a50d5efc593e7199705ea10c`
**Window:** last 7 days
**Total ledger rows:** `18363`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.3% | 58/18363 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18363 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18363 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18130 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 162 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 71 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18363 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18130 |
| `crypto-oversold-bounce` | 162 |
| `crypto-breakdown` | 71 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18363 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18259 |
| `BLOCK` | 58 |
| `ALERT_ONLY` | 46 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18363 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18363 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18259 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
