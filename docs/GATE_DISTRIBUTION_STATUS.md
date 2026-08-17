# Gate Distribution Status (v3.24.0)

**Generated:** `2026-08-17T05:08:52.158048+00:00`
**As of:** `2026-08-17T05:08:51.861418+00:00`
**Git HEAD:** `ec5b641f4a25cd0098052a912f45d60c408b308e`
**Window:** last 7 days
**Total ledger rows:** `19505`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.7% | 138/19505 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 19505 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 19505 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18935 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 482 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 88 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 19505 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18935 |
| `crypto-oversold-bounce` | 482 |
| `crypto-breakdown` | 88 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 19505 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 19258 |
| `BLOCK` | 138 |
| `ALERT_ONLY` | 109 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 19505 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 19505 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 19258 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
