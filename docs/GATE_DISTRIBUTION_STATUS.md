# Gate Distribution Status (v3.24.0)

**Generated:** `2026-06-26T08:07:31.694827+00:00`
**As of:** `2026-06-26T08:07:31.432682+00:00`
**Git HEAD:** `3bfaffb9279abc66f3685f44a2c01c6f27810afe`
**Window:** last 7 days
**Total ledger rows:** `18788`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 89/18788 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18788 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18788 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18319 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 276 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 193 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18788 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18319 |
| `crypto-oversold-bounce` | 276 |
| `crypto-breakdown` | 193 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18788 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18626 |
| `BLOCK` | 89 |
| `ALERT_ONLY` | 73 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18788 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18788 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18626 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
