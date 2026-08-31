# Gate Distribution Status (v3.24.0)

**Generated:** `2026-08-31T11:02:57.780425+00:00`
**As of:** `2026-08-31T11:02:57.503362+00:00`
**Git HEAD:** `f482735959ed842b7cc9b43e032515a46f0698b1`
**Window:** last 7 days
**Total ledger rows:** `18758`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.2% | 37/18758 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18758 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18758 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18640 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 70 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 48 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18758 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18640 |
| `crypto-oversold-bounce` | 70 |
| `crypto-breakdown` | 48 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18758 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18700 |
| `BLOCK` | 37 |
| `ALERT_ONLY` | 21 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18758 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18758 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18700 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
