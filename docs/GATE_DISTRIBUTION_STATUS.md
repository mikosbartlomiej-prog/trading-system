# Gate Distribution Status (v3.24.0)

**Generated:** `2026-09-02T08:57:20.690819+00:00`
**As of:** `2026-09-02T08:57:20.475910+00:00`
**Git HEAD:** `9e50f273002e8fde104dceda2bb5d761921e73ef`
**Window:** last 7 days
**Total ledger rows:** `18346`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 86/18346 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18346 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18346 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18109 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 146 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 91 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18346 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18109 |
| `crypto-oversold-bounce` | 146 |
| `crypto-breakdown` | 91 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18346 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18250 |
| `BLOCK` | 86 |
| `ALERT_ONLY` | 10 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18346 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18346 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18250 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
