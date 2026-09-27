# Gate Distribution Status (v3.24.0)

**Generated:** `2026-09-27T10:09:04.019822+00:00`
**As of:** `2026-09-27T10:09:03.765508+00:00`
**Git HEAD:** `c9e206fbd3563adc8e2cc9236c31fb20ff9f76b3`
**Window:** last 7 days
**Total ledger rows:** `18605`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.3% | 58/18605 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18605 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18605 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18248 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 310 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 47 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18605 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18248 |
| `crypto-oversold-bounce` | 310 |
| `crypto-breakdown` | 47 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18605 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18450 |
| `ALERT_ONLY` | 97 |
| `BLOCK` | 58 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18605 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18605 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18450 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
