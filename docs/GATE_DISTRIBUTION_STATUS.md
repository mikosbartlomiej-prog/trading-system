# Gate Distribution Status (v3.24.0)

**Generated:** `2026-09-16T09:26:09.911232+00:00`
**As of:** `2026-09-16T09:26:09.657031+00:00`
**Git HEAD:** `edff290dea5ed0e0ec907accf06a57fb0c58462e`
**Window:** last 7 days
**Total ledger rows:** `18221`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.3% | 51/18221 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18221 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18221 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17968 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 178 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 75 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18221 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17968 |
| `crypto-oversold-bounce` | 178 |
| `crypto-breakdown` | 75 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18221 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18120 |
| `BLOCK` | 51 |
| `ALERT_ONLY` | 50 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18221 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18221 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18120 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
