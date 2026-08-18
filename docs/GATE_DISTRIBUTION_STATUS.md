# Gate Distribution Status (v3.24.0)

**Generated:** `2026-08-18T05:02:45.057567+00:00`
**As of:** `2026-08-18T05:02:44.769583+00:00`
**Git HEAD:** `1278ad17fd1d380cb5182de2172634a813368cff`
**Window:** last 7 days
**Total ledger rows:** `19624`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 1.1% | 207/19624 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 19624 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 19624 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18878 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 620 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 126 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 19624 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18878 |
| `crypto-oversold-bounce` | 620 |
| `crypto-breakdown` | 126 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 19624 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 19308 |
| `BLOCK` | 207 |
| `ALERT_ONLY` | 109 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 19624 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 19624 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 19308 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
