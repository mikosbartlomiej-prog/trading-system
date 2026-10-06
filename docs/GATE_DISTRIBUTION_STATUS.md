# Gate Distribution Status (v3.24.0)

**Generated:** `2026-10-06T11:26:17.636862+00:00`
**As of:** `2026-10-06T11:26:17.444685+00:00`
**Git HEAD:** `294759eaf5f78f4f2e4cb03347dc53aecd7dfbe8`
**Window:** last 7 days
**Total ledger rows:** `18255`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.3% | 59/18255 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18255 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18255 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17857 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 290 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 108 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18255 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17857 |
| `crypto-oversold-bounce` | 290 |
| `crypto-breakdown` | 108 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18255 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18110 |
| `ALERT_ONLY` | 86 |
| `BLOCK` | 59 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18255 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18255 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18110 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
