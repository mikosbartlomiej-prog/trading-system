# Gate Distribution Status (v3.24.0)

**Generated:** `2026-08-05T07:14:53.454612+00:00`
**As of:** `2026-08-05T07:14:53.196111+00:00`
**Git HEAD:** `413cc0dab303259282150c391da25c5ee7bc8e1a`
**Window:** last 7 days
**Total ledger rows:** `18740`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 100/18740 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18740 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18740 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18174 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 426 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 140 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18740 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18174 |
| `crypto-oversold-bounce` | 426 |
| `crypto-breakdown` | 140 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18740 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18508 |
| `ALERT_ONLY` | 132 |
| `BLOCK` | 100 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18740 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18740 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18508 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
