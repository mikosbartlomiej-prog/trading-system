# Gate Distribution Status (v3.24.0)

**Generated:** `2026-08-10T05:55:45.165051+00:00`
**As of:** `2026-08-10T05:55:44.890440+00:00`
**Git HEAD:** `3ff687882c584f5683a7c34bf66ce2389e824138`
**Window:** last 7 days
**Total ledger rows:** `18180`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.9% | 160/18180 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18180 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18180 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17652 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 440 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 88 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18180 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17652 |
| `crypto-oversold-bounce` | 440 |
| `crypto-breakdown` | 88 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18180 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 17960 |
| `BLOCK` | 160 |
| `ALERT_ONLY` | 60 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18180 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18180 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 17960 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
