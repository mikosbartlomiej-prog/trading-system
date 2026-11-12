# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-12T13:06:32.180642+00:00`
**As of:** `2026-11-12T13:06:31.909514+00:00`
**Git HEAD:** `f88c64c1d2236334d574228c715870ba9d66f948`
**Window:** last 7 days
**Total ledger rows:** `18755`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.7% | 124/18755 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18755 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18755 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18118 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 440 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 197 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18755 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18118 |
| `crypto-oversold-bounce` | 440 |
| `crypto-breakdown` | 197 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18755 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18517 |
| `BLOCK` | 124 |
| `ALERT_ONLY` | 114 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18755 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18755 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18517 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
