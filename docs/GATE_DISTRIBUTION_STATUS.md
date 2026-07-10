# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-10T07:58:50.411116+00:00`
**As of:** `2026-07-10T07:58:50.142676+00:00`
**Git HEAD:** `38e5fb6447aeac4cb64c951b1dd3cb2d0f33624c`
**Window:** last 7 days
**Total ledger rows:** `18461`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 84/18461 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18461 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18461 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18321 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 140 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18461 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18321 |
| `crypto-oversold-bounce` | 140 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18461 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18340 |
| `BLOCK` | 84 |
| `ALERT_ONLY` | 37 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18461 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18461 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18340 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
