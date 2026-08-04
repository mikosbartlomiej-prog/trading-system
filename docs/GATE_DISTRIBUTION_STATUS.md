# Gate Distribution Status (v3.24.0)

**Generated:** `2026-08-04T07:13:12.782151+00:00`
**As of:** `2026-08-04T07:13:12.504616+00:00`
**Git HEAD:** `d1d42afc3fccc6198db354ead8a9b1d7e34f657f`
**Window:** last 7 days
**Total ledger rows:** `18796`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 88/18796 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18796 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18796 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18290 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 378 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 128 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18796 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18290 |
| `crypto-oversold-bounce` | 378 |
| `crypto-breakdown` | 128 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18796 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18588 |
| `ALERT_ONLY` | 120 |
| `BLOCK` | 88 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18796 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18796 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18588 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
