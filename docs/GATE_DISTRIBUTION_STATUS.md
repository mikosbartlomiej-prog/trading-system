# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-18T13:19:53.389436+00:00`
**As of:** `2026-11-18T13:19:53.151571+00:00`
**Git HEAD:** `a88c2e70566715ea34b4c9e1d5d74765ffbaf535`
**Window:** last 7 days
**Total ledger rows:** `18829`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 1.2% | 218/18829 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18829 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18829 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17606 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 814 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 409 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18829 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17606 |
| `crypto-oversold-bounce` | 814 |
| `crypto-breakdown` | 409 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18829 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18410 |
| `BLOCK` | 218 |
| `ALERT_ONLY` | 201 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18829 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18829 |

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
