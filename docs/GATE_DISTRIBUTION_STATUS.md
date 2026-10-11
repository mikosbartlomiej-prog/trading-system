# Gate Distribution Status (v3.24.0)

**Generated:** `2026-10-11T10:58:40.431909+00:00`
**As of:** `2026-10-11T10:58:40.178265+00:00`
**Git HEAD:** `eb0204337d0dd9bee59741542dbbd2605afcb659`
**Window:** last 7 days
**Total ledger rows:** `18200`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.4% | 79/18200 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18200 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18200 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17560 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 440 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 200 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18200 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17560 |
| `crypto-oversold-bounce` | 440 |
| `crypto-breakdown` | 200 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18200 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 17980 |
| `ALERT_ONLY` | 141 |
| `BLOCK` | 79 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18200 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18200 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 17980 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
