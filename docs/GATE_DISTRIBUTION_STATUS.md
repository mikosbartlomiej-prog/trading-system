# Gate Distribution Status (v3.24.0)

**Generated:** `2026-08-01T07:02:35.587823+00:00`
**As of:** `2026-08-01T07:02:35.333202+00:00`
**Git HEAD:** `da36e25c38c1b56a8761c1937d5c75bd59344ffa`
**Window:** last 7 days
**Total ledger rows:** `18755`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.7% | 139/18755 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18755 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18755 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18130 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 448 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 177 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18755 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18130 |
| `crypto-oversold-bounce` | 448 |
| `crypto-breakdown` | 177 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18755 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18530 |
| `BLOCK` | 139 |
| `ALERT_ONLY` | 86 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18755 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18755 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18530 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
