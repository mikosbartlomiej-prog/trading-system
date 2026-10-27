# Gate Distribution Status (v3.24.0)

**Generated:** `2026-10-27T09:57:58.883738+00:00`
**As of:** `2026-10-27T09:57:58.680646+00:00`
**Git HEAD:** `0b6d065f33184558227530ba708830d596c11e8c`
**Window:** last 7 days
**Total ledger rows:** `18449`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.2% | 40/18449 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18449 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18449 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17966 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 318 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 165 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18449 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17966 |
| `crypto-oversold-bounce` | 318 |
| `crypto-breakdown` | 165 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18449 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18290 |
| `ALERT_ONLY` | 119 |
| `BLOCK` | 40 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18449 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18449 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18290 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
