# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-17T13:45:07.801807+00:00`
**As of:** `2026-11-17T13:45:07.630857+00:00`
**Git HEAD:** `01bec03e7c92518aa215bb40d3f2c5d6ced30497`
**Window:** last 7 days
**Total ledger rows:** `18808`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 1.2% | 230/18808 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18808 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18808 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17626 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 792 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 390 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18808 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17626 |
| `crypto-oversold-bounce` | 792 |
| `crypto-breakdown` | 390 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18808 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18400 |
| `BLOCK` | 230 |
| `ALERT_ONLY` | 178 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18808 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18808 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18400 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
