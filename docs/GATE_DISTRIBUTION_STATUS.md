# Gate Distribution Status (v3.24.0)

**Generated:** `2026-08-15T04:57:18.293950+00:00`
**As of:** `2026-08-15T04:57:18.069522+00:00`
**Git HEAD:** `08a1ff56cd9e948a3ff91111c2c805374f637778`
**Window:** last 7 days
**Total ledger rows:** `19126`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 1.2% | 222/19126 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 19126 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 19126 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18353 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 644 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 129 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 19126 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18353 |
| `crypto-oversold-bounce` | 644 |
| `crypto-breakdown` | 129 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 19126 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18798 |
| `BLOCK` | 222 |
| `ALERT_ONLY` | 106 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 19126 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 19126 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18798 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
