# Gate Distribution Status (v3.24.0)

**Generated:** `2026-09-18T09:08:05.680995+00:00`
**As of:** `2026-09-18T09:08:05.413104+00:00`
**Git HEAD:** `691bc4b7b34c8aec8c08a310cf075450ec3fdc4d`
**Window:** last 7 days
**Total ledger rows:** `18464`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.3% | 59/18464 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18464 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18464 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18121 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 268 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 75 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18464 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18121 |
| `crypto-oversold-bounce` | 268 |
| `crypto-breakdown` | 75 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18464 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18330 |
| `ALERT_ONLY` | 75 |
| `BLOCK` | 59 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18464 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18464 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18330 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
