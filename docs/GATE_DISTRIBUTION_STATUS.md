# Gate Distribution Status (v3.24.0)

**Generated:** `2026-07-31T07:22:09.055193+00:00`
**As of:** `2026-07-31T07:22:08.792360+00:00`
**Git HEAD:** `dfd23fbe1c83c8706c2dad11b529354efdb8f98a`
**Window:** last 7 days
**Total ledger rows:** `18777`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.7% | 138/18777 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18777 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18777 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18139 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 474 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 164 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18777 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18139 |
| `crypto-oversold-bounce` | 474 |
| `crypto-breakdown` | 164 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18777 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18540 |
| `BLOCK` | 138 |
| `ALERT_ONLY` | 99 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18777 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18777 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18540 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
