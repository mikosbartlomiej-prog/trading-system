# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-28T13:27:52.428068+00:00`
**As of:** `2026-11-28T13:27:52.251149+00:00`
**Git HEAD:** `54ba40e71075af6dfc6dd67ee93bc6a30590e401`
**Window:** last 7 days
**Total ledger rows:** `18555`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.7% | 132/18555 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18555 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18555 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17986 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 307 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 262 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18555 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17986 |
| `crypto-breakdown` | 307 |
| `crypto-oversold-bounce` | 262 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18555 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18400 |
| `BLOCK` | 132 |
| `ALERT_ONLY` | 23 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18555 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18555 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18400 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
