# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-16T13:03:41.991865+00:00`
**As of:** `2026-11-16T13:03:41.728722+00:00`
**Git HEAD:** `073601d2c74a8854655ec986e43e7f20085758f8`
**Window:** last 7 days
**Total ledger rows:** `18773`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 1.1% | 208/18773 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18773 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18773 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17788 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 702 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 283 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18773 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17788 |
| `crypto-oversold-bounce` | 702 |
| `crypto-breakdown` | 283 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18773 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18410 |
| `BLOCK` | 208 |
| `ALERT_ONLY` | 155 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18773 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18773 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18410 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
