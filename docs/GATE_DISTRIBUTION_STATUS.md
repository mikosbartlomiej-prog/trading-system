# Gate Distribution Status (v3.24.0)

**Generated:** `2026-10-26T10:24:24.690021+00:00`
**As of:** `2026-10-26T10:24:24.404929+00:00`
**Git HEAD:** `9fe5af9e1bbe8f612ed3fcc45fac6ddc253da67b`
**Window:** last 7 days
**Total ledger rows:** `18530`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.2% | 39/18530 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18530 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18530 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18003 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 340 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 187 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18530 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18003 |
| `crypto-oversold-bounce` | 340 |
| `crypto-breakdown` | 187 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18530 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18360 |
| `ALERT_ONLY` | 131 |
| `BLOCK` | 39 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18530 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18530 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18360 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
