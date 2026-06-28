# Gate Distribution Status (v3.24.0)

**Generated:** `2026-06-28T08:02:52.628461+00:00`
**As of:** `2026-06-28T08:02:52.370969+00:00`
**Git HEAD:** `621ba1044c77878bdad588ea1b734e949b6cac18`
**Window:** last 7 days
**Total ledger rows:** `18772`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.8% | 159/18772 rows blocked at the confidence gate (BLOCK) |

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
| `crypto-momentum` | `NO_BLOCKER` | 17987 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 474 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 311 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18772 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17987 |
| `crypto-oversold-bounce` | 474 |
| `crypto-breakdown` | 311 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18772 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18505 |
| `BLOCK` | 159 |
| `ALERT_ONLY` | 108 |

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
| `P2` | 18505 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
