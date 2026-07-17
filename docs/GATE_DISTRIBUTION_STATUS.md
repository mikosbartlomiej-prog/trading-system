# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-17T06:38:15.422298+00:00`
**As of:** `2026-07-17T06:38:15.191664+00:00`
**Git HEAD:** `94ffd271b643a9b405b16dbeb223ba58d59610ba`
**Window:** last 7 days
**Total ledger rows:** `18847`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.7% | 125/18847 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18847 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18847 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18361 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 374 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 112 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18847 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18361 |
| `crypto-oversold-bounce` | 374 |
| `crypto-breakdown` | 112 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18847 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18660 |
| `BLOCK` | 125 |
| `ALERT_ONLY` | 62 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18847 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18847 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18660 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
