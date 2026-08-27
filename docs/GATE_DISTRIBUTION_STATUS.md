# Gate Distribution Status (v3.24.0)

**Generated:** `2026-08-27T15:24:40.780569+00:00`
**As of:** `2026-08-27T15:24:40.528830+00:00`
**Git HEAD:** `7e103b427312cd70b87d7081fba6cd084d587aca`
**Window:** last 7 days
**Total ledger rows:** `20605`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.1% | 25/20605 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 20605 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 20605 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 20558 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 25 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 22 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 20605 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 20558 |
| `crypto-breakdown` | 25 |
| `crypto-oversold-bounce` | 22 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 20605 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 20569 |
| `BLOCK` | 25 |
| `ALERT_ONLY` | 11 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 20605 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 20605 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 20569 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
