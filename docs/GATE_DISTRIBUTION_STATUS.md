# Gate Distribution Status (v3.24.0)

**Generated:** `2026-10-17T08:44:41.583290+00:00`
**As of:** `2026-10-17T08:44:41.334614+00:00`
**Git HEAD:** `2d2b1623b8c6bad1a4e3af3040b1db0cf38f6d0f`
**Window:** last 7 days
**Total ledger rows:** `18172`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.3% | 47/18172 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18172 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18172 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17616 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 392 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 164 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18172 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17616 |
| `crypto-breakdown` | 392 |
| `crypto-oversold-bounce` | 164 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18172 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18090 |
| `BLOCK` | 47 |
| `ALERT_ONLY` | 35 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18172 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18172 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18090 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
