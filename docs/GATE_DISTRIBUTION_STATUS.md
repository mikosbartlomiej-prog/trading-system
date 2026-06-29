# Gate Distribution Status (v3.24.0)

**Generated:** `2026-06-29T09:15:38.301551+00:00`
**As of:** `2026-06-29T09:15:38.030337+00:00`
**Git HEAD:** `9502482d296ec0c2c5728cfcd2b4c5b19a33fed5`
**Window:** last 7 days
**Total ledger rows:** `19012`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.8% | 159/19012 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 19012 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 19012 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18182 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 454 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 376 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 19012 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18182 |
| `crypto-oversold-bounce` | 454 |
| `crypto-breakdown` | 376 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 19012 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18755 |
| `BLOCK` | 159 |
| `ALERT_ONLY` | 98 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 19012 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 19012 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18755 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
