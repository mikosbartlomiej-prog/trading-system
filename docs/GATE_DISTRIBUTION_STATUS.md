# Gate Distribution Status (v3.24.0)

**Generated:** `2026-09-06T08:47:29.974890+00:00`
**As of:** `2026-09-06T08:47:29.723819+00:00`
**Git HEAD:** `447169e966719c6a612c315dc452ab8cdf7215b3`
**Window:** last 7 days
**Total ledger rows:** `18103`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 85/18103 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18103 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18103 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17773 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 248 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 82 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18103 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17773 |
| `crypto-oversold-bounce` | 248 |
| `crypto-breakdown` | 82 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18103 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 17970 |
| `BLOCK` | 85 |
| `ALERT_ONLY` | 48 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18103 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18103 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 17970 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
