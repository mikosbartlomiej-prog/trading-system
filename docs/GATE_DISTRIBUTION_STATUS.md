# Gate Distribution Status (v3.24.0)

**Generated:** `2026-09-13T09:40:40.383069+00:00`
**As of:** `2026-09-13T09:40:40.139847+00:00`
**Git HEAD:** `1d9324fbf0392b9ae7c387d5d15bfc46bc46f88b`
**Window:** last 7 days
**Total ledger rows:** `17917`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.1% | 24/17917 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 17917 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 17917 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17841 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 50 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 26 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 17917 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17841 |
| `crypto-oversold-bounce` | 50 |
| `crypto-breakdown` | 26 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 17917 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 17880 |
| `BLOCK` | 24 |
| `ALERT_ONLY` | 13 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 17917 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 17917 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 17880 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
