# Gate Distribution Status (v3.24.0)

**Generated:** `2026-08-09T05:29:18.395354+00:00`
**As of:** `2026-08-09T05:29:18.150944+00:00`
**Git HEAD:** `467de6e74baea9d8b00d51aa1dc738604d708690`
**Window:** last 7 days
**Total ledger rows:** `17823`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.4% | 74/17823 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 17823 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 17823 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17349 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 378 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 96 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 17823 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17349 |
| `crypto-oversold-bounce` | 378 |
| `crypto-breakdown` | 96 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 17823 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 17628 |
| `ALERT_ONLY` | 121 |
| `BLOCK` | 74 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 17823 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 17823 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 17628 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
