# Gate Distribution Status (v3.24.0)

**Generated:** `2026-09-05T08:29:59.685961+00:00`
**As of:** `2026-09-05T08:29:59.443647+00:00`
**Git HEAD:** `fce4f70b01bf0b09386e85f9938270bc8bf5807f`
**Window:** last 7 days
**Total ledger rows:** `18070`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 85/18070 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18070 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18070 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17766 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 222 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 82 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18070 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17766 |
| `crypto-oversold-bounce` | 222 |
| `crypto-breakdown` | 82 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18070 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 17950 |
| `BLOCK` | 85 |
| `ALERT_ONLY` | 35 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18070 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18070 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 17950 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
