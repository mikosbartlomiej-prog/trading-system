# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-09T08:01:28.071498+00:00`
**As of:** `2026-07-09T08:01:27.860133+00:00`
**Git HEAD:** `37515dd4c44df0778779df78b30f9b23f806a7f2`
**Window:** last 7 days
**Total ledger rows:** `18732`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 91/18732 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18732 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18732 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18506 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 202 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 24 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18732 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18506 |
| `crypto-oversold-bounce` | 202 |
| `crypto-breakdown` | 24 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18732 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18580 |
| `BLOCK` | 91 |
| `ALERT_ONLY` | 61 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18732 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18732 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18580 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
