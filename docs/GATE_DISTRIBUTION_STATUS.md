# Gate Distribution Status (v3.24.0)

**Generated:** `2026-06-22T10:21:45.966446+00:00`
**As of:** `2026-06-22T10:21:45.698105+00:00`
**Git HEAD:** `8e6ad465f974797eaeff9ab7b916c9b56320ed4c`
**Window:** last 7 days
**Total ledger rows:** `18004`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.3% | 49/18004 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18004 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18004 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17594 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 290 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 120 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18004 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17594 |
| `crypto-oversold-bounce` | 290 |
| `crypto-breakdown` | 120 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18004 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 17859 |
| `ALERT_ONLY` | 96 |
| `BLOCK` | 49 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18004 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18004 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 17859 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
