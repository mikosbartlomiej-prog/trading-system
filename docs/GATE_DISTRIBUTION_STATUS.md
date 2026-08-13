# Gate Distribution Status (v3.24.0)

**Generated:** `2026-08-13T05:57:24.136417+00:00`
**As of:** `2026-08-13T05:57:23.840682+00:00`
**Git HEAD:** `4be67a1a6357e7c6896524cbe1a5ec8dfd886908`
**Window:** last 7 days
**Total ledger rows:** `19226`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.6% | 123/19226 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 19226 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 19226 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18861 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 312 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 53 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 19226 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18861 |
| `crypto-oversold-bounce` | 312 |
| `crypto-breakdown` | 53 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 19226 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 19070 |
| `BLOCK` | 123 |
| `ALERT_ONLY` | 33 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 19226 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 19226 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 19070 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
