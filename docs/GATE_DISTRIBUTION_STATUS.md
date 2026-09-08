# Gate Distribution Status (v3.24.0)

**Generated:** `2026-09-08T08:59:40.715233+00:00`
**As of:** `2026-09-08T08:59:40.472432+00:00`
**Git HEAD:** `fbfd56d891ff6f80ce08cbe71fec6731692a8923`
**Window:** last 7 days
**Total ledger rows:** `18102`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.2% | 34/18102 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18102 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18102 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17951 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 126 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 25 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18102 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17951 |
| `crypto-oversold-bounce` | 126 |
| `crypto-breakdown` | 25 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18102 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18030 |
| `ALERT_ONLY` | 38 |
| `BLOCK` | 34 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18102 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18102 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18030 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
