# Gate Distribution Status (v3.24.0)

**Generated:** `2026-09-23T09:26:56.330246+00:00`
**As of:** `2026-09-23T09:26:56.110179+00:00`
**Git HEAD:** `a122128e59205a02c306ea2d96e047ed27332a0c`
**Window:** last 7 days
**Total ledger rows:** `18601`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 91/18601 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18601 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18601 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18243 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 252 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 106 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18601 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18243 |
| `crypto-oversold-bounce` | 252 |
| `crypto-breakdown` | 106 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18601 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18450 |
| `BLOCK` | 91 |
| `ALERT_ONLY` | 60 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18601 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18601 |

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
