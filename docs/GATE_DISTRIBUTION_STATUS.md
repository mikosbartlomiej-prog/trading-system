# Gate Distribution Status (v3.24.0)

**Generated:** `2026-06-23T08:03:29.952718+00:00`
**As of:** `2026-06-23T08:03:29.686989+00:00`
**Git HEAD:** `f6637a939ae9a9a158ae2368c5d4b65570c364f4`
**Window:** last 7 days
**Total ledger rows:** `18722`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.3% | 49/18722 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18722 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18722 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18312 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 290 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 120 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18722 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18312 |
| `crypto-oversold-bounce` | 290 |
| `crypto-breakdown` | 120 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18722 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18577 |
| `ALERT_ONLY` | 96 |
| `BLOCK` | 49 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18722 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18722 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18577 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
