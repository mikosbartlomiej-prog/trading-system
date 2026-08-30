# Gate Distribution Status (v3.24.0)

**Generated:** `2026-08-30T10:03:43.227114+00:00`
**As of:** `2026-08-30T10:03:43.010269+00:00`
**Git HEAD:** `fc3beb4745625597ea05883db0a98d345c9cd290`
**Window:** last 7 days
**Total ledger rows:** `18786`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.2% | 35/18786 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18786 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18786 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18693 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 47 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 46 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18786 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18693 |
| `crypto-breakdown` | 47 |
| `crypto-oversold-bounce` | 46 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18786 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18740 |
| `BLOCK` | 35 |
| `ALERT_ONLY` | 11 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18786 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18786 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18740 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
