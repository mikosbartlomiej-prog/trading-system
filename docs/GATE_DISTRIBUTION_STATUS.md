# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-09T13:13:50.289799+00:00`
**As of:** `2026-11-09T13:13:50.107821+00:00`
**Git HEAD:** `f4ad55cab0e2fff7f1ab613111b24dd77e2832c3`
**Window:** last 7 days
**Total ledger rows:** `18772`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.6% | 111/18772 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18772 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18772 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18214 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 394 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 164 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18772 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18214 |
| `crypto-oversold-bounce` | 394 |
| `crypto-breakdown` | 164 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18772 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18557 |
| `BLOCK` | 111 |
| `ALERT_ONLY` | 104 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18772 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18772 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18557 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
