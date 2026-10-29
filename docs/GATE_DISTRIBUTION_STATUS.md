# Gate Distribution Status (v3.24.0)

**Generated:** `2026-10-29T11:02:17.867972+00:00`
**As of:** `2026-10-29T11:02:17.589735+00:00`
**Git HEAD:** `84d2eaf586210fe83b3e994752eedbf93075ac1d`
**Window:** last 7 days
**Total ledger rows:** `18629`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 87/18629 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18629 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18629 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18089 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 412 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 128 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18629 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18089 |
| `crypto-oversold-bounce` | 412 |
| `crypto-breakdown` | 128 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18629 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18400 |
| `ALERT_ONLY` | 142 |
| `BLOCK` | 87 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18629 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18629 |

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
