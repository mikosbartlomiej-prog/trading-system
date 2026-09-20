# Gate Distribution Status (v3.24.0)

**Generated:** `2026-09-20T09:24:52.540727+00:00`
**As of:** `2026-09-20T09:24:52.273841+00:00`
**Git HEAD:** `9f8261e340502a6ca3c5597fd1a3bebdeeeaca84`
**Window:** last 7 days
**Total ledger rows:** `18539`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.6% | 113/18539 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18539 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18539 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18156 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 288 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 95 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18539 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18156 |
| `crypto-oversold-bounce` | 288 |
| `crypto-breakdown` | 95 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18539 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18370 |
| `BLOCK` | 113 |
| `ALERT_ONLY` | 56 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18539 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18539 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18370 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
