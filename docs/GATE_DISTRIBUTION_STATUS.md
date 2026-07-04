# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-04T07:22:16.968054+00:00`
**As of:** `2026-07-04T07:22:16.698407+00:00`
**Git HEAD:** `dfd4fb2a95f1cf52f40ea9b6b49ef4ce7ec10fb4`
**Window:** last 7 days
**Total ledger rows:** `18690`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 101/18690 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18690 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18690 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18315 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 286 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 89 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18690 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18315 |
| `crypto-oversold-bounce` | 286 |
| `crypto-breakdown` | 89 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18690 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18528 |
| `BLOCK` | 101 |
| `ALERT_ONLY` | 61 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18690 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18690 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18528 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
