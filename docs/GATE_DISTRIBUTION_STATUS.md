# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-25T06:38:04.047287+00:00`
**As of:** `2026-07-25T06:38:03.814093+00:00`
**Git HEAD:** `d9b96924b067c5e371ca2980db1b359e3d3a58e3`
**Window:** last 7 days
**Total ledger rows:** `14204`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 68/14204 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 14204 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 14204 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 14011 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 184 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 9 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 14204 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 14011 |
| `crypto-oversold-bounce` | 184 |
| `crypto-breakdown` | 9 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 14204 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 14100 |
| `BLOCK` | 68 |
| `ALERT_ONLY` | 36 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 14204 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 14204 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 14100 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
