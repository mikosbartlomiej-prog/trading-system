# Gate Distribution Status (v3.24.0)

**Generated:** `2026-10-07T11:16:49.531031+00:00`
**As of:** `2026-10-07T11:16:49.270542+00:00`
**Git HEAD:** `b54b4771582a7f5460f032c8be7937ca4fd7228a`
**Window:** last 7 days
**Total ledger rows:** `18235`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.4% | 71/18235 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18235 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18235 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17837 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 290 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 108 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18235 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17837 |
| `crypto-oversold-bounce` | 290 |
| `crypto-breakdown` | 108 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18235 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18090 |
| `ALERT_ONLY` | 74 |
| `BLOCK` | 71 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18235 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18235 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18090 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
