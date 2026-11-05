# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-05T12:39:52.309059+00:00`
**As of:** `2026-11-05T12:39:52.089741+00:00`
**Git HEAD:** `a456a22a55ac304f04db6218092dafad98dfe315`
**Window:** last 7 days
**Total ledger rows:** `18506`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.6% | 108/18506 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18506 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18506 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18068 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 240 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 198 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18506 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18068 |
| `crypto-oversold-bounce` | 240 |
| `crypto-breakdown` | 198 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18506 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18386 |
| `BLOCK` | 108 |
| `ALERT_ONLY` | 12 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18506 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18506 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18386 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
