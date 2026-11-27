# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-27T14:11:13.449771+00:00`
**As of:** `2026-11-27T14:11:13.168016+00:00`
**Git HEAD:** `24d47a4fa9d0bbf121c02f7cd405d3dbb01904ac`
**Window:** last 7 days
**Total ledger rows:** `18679`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.8% | 144/18679 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18679 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18679 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18110 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 310 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 259 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18679 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18110 |
| `crypto-oversold-bounce` | 310 |
| `crypto-breakdown` | 259 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18679 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18500 |
| `BLOCK` | 144 |
| `ALERT_ONLY` | 35 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18679 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18679 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18500 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
