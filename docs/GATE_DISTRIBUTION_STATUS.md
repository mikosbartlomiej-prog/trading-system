# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-18T06:27:56.980049+00:00`
**As of:** `2026-07-18T06:27:56.714636+00:00`
**Git HEAD:** `3d2fb04d8c1a8b26c736c3c3d8d4744ab24c2f85`
**Window:** last 7 days
**Total ledger rows:** `18668`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.4% | 73/18668 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18668 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18668 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18397 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 196 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 75 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18668 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18397 |
| `crypto-oversold-bounce` | 196 |
| `crypto-breakdown` | 75 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18668 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18570 |
| `BLOCK` | 73 |
| `ALERT_ONLY` | 25 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18668 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18668 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18570 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
