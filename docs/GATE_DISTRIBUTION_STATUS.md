# Gate Distribution Status (v3.24.0)

**Generated:** `2026-10-24T09:01:21.417633+00:00`
**As of:** `2026-10-24T09:01:21.210741+00:00`
**Git HEAD:** `2e1a6dcae95d2f686988fe35fdd15cad44639e1e`
**Window:** last 7 days
**Total ledger rows:** `18245`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.4% | 71/18245 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18245 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18245 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17890 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 189 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 166 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18245 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17890 |
| `crypto-breakdown` | 189 |
| `crypto-oversold-bounce` | 166 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18245 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18150 |
| `BLOCK` | 71 |
| `ALERT_ONLY` | 24 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18245 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18245 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18150 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
