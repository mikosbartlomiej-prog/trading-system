# Gate Distribution Status (v3.24.0)

**Generated:** `2026-09-25T09:44:50.012169+00:00`
**As of:** `2026-09-25T09:44:49.784829+00:00`
**Git HEAD:** `f6210f3de286a092e5a20deb93b8910ed4d453cd`
**Window:** last 7 days
**Total ledger rows:** `18504`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.3% | 61/18504 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18504 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18504 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18302 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 118 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 84 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18504 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18302 |
| `crypto-oversold-bounce` | 118 |
| `crypto-breakdown` | 84 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18504 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18420 |
| `BLOCK` | 61 |
| `ALERT_ONLY` | 23 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18504 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18504 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18420 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
