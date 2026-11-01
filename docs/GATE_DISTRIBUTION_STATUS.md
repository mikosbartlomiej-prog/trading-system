# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-01T11:26:44.631219+00:00`
**As of:** `2026-11-01T11:26:44.455805+00:00`
**Git HEAD:** `d36ba485e49d12a00332930bb0c2ffcf40cd6b1a`
**Window:** last 7 days
**Total ledger rows:** `18425`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.5% | 96/18425 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18425 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18425 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18138 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 192 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 95 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18425 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18138 |
| `crypto-oversold-bounce` | 192 |
| `crypto-breakdown` | 95 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18425 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18306 |
| `BLOCK` | 96 |
| `ALERT_ONLY` | 23 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18425 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18425 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18306 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
