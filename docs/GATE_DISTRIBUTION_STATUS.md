# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-12T07:07:00.060888+00:00`
**As of:** `2026-07-12T07:06:59.811658+00:00`
**Git HEAD:** `c99cf224c46a53558fe83fa29272d988585d8860`
**Window:** last 7 days
**Total ledger rows:** `18457`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.6% | 111/18457 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18457 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18457 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18013 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 368 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 76 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18457 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18013 |
| `crypto-oversold-bounce` | 368 |
| `crypto-breakdown` | 76 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18457 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18260 |
| `BLOCK` | 111 |
| `ALERT_ONLY` | 86 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18457 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18457 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18260 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
