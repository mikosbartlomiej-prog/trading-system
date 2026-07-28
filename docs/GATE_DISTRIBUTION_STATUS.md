# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-28T07:13:13.782372+00:00`
**As of:** `2026-07-28T07:13:13.523661+00:00`
**Git HEAD:** `4d3588c4f236aa6a10ff6fe2036a4aff2b7f6da5`
**Window:** last 7 days
**Total ledger rows:** `18672`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 99/18672 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18672 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18672 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18283 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 300 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 89 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18672 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18283 |
| `crypto-oversold-bounce` | 300 |
| `crypto-breakdown` | 89 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18672 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18510 |
| `BLOCK` | 99 |
| `ALERT_ONLY` | 63 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18672 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18672 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18510 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
