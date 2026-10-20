# Gate Distribution Status (v3.24.0)

**Generated:** `2026-10-20T09:34:18.761590+00:00`
**As of:** `2026-10-20T09:34:18.566411+00:00`
**Git HEAD:** `982f9baaf47d24b61dc4a3789cc02e8bf306dbcd`
**Window:** last 7 days
**Total ledger rows:** `18456`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.9% | 167/18456 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18456 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18456 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17745 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 428 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 283 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18456 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17745 |
| `crypto-oversold-bounce` | 428 |
| `crypto-breakdown` | 283 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18456 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18230 |
| `BLOCK` | 167 |
| `ALERT_ONLY` | 59 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18456 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18456 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18230 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
