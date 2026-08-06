# Gate Distribution Status (v3.24.0)

**Generated:** `2026-08-06T07:15:57.406794+00:00`
**As of:** `2026-08-06T07:15:57.128885+00:00`
**Git HEAD:** `717b0a1e883e455077187d6e4385ad43ce1d72cd`
**Window:** last 7 days
**Total ledger rows:** `18651`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.2% | 41/18651 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18651 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18651 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18259 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 308 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 84 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18651 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18259 |
| `crypto-oversold-bounce` | 308 |
| `crypto-breakdown` | 84 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18651 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18478 |
| `ALERT_ONLY` | 132 |
| `BLOCK` | 41 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18651 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18651 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18478 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
