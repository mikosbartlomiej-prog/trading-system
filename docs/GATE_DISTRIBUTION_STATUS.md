# Gate Distribution Status (v3.24.0)

**Generated:** `2026-10-03T10:00:02.488268+00:00`
**As of:** `2026-10-03T10:00:02.238804+00:00`
**Git HEAD:** `9848b712d9e47c2456bb58e99c946c5347409da8`
**Window:** last 7 days
**Total ledger rows:** `18323`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.3% | 58/18323 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18323 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18323 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18090 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 162 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 71 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18323 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18090 |
| `crypto-oversold-bounce` | 162 |
| `crypto-breakdown` | 71 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18323 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18219 |
| `BLOCK` | 58 |
| `ALERT_ONLY` | 46 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18323 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18323 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18219 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
