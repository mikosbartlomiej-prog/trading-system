# Gate Distribution Status (v3.24.0)

**Generated:** `2026-09-17T09:35:38.408787+00:00`
**As of:** `2026-09-17T09:35:38.237871+00:00`
**Git HEAD:** `fde79cdc2a12d85b8513467026fdbfde0ceb6332`
**Window:** last 7 days
**Total ledger rows:** `18308`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.3% | 46/18308 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18308 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18308 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18017 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 216 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 75 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18308 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18017 |
| `crypto-oversold-bounce` | 216 |
| `crypto-breakdown` | 75 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18308 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18200 |
| `ALERT_ONLY` | 62 |
| `BLOCK` | 46 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18308 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18308 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18200 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
