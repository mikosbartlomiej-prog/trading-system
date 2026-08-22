# Gate Distribution Status (v3.24.0)

**Generated:** `2026-08-22T05:00:14.717590+00:00`
**As of:** `2026-08-22T05:00:14.473348+00:00`
**Git HEAD:** `6424725902035c4cefe30be380b792218ea2ee0b`
**Window:** last 7 days
**Total ledger rows:** `19904`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.7% | 137/19904 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 19904 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 19904 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 19506 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 348 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 50 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 19904 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 19506 |
| `crypto-oversold-bounce` | 348 |
| `crypto-breakdown` | 50 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 19904 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 19730 |
| `BLOCK` | 137 |
| `ALERT_ONLY` | 37 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 19904 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 19904 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 19730 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
