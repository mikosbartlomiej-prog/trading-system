# Gate Distribution Status (v3.24.0)

**Generated:** `2026-10-13T12:03:05.331161+00:00`
**As of:** `2026-10-13T12:03:05.141942+00:00`
**Git HEAD:** `789960c425a724406afee158bd2d38d1dd632503`
**Window:** last 7 days
**Total ledger rows:** `18501`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.3% | 55/18501 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18501 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18501 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17820 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 362 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 319 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18501 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17820 |
| `crypto-oversold-bounce` | 362 |
| `crypto-breakdown` | 319 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18501 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18320 |
| `ALERT_ONLY` | 126 |
| `BLOCK` | 55 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18501 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18501 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18320 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
