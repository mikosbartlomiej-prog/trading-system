# Gate Distribution Status (v3.24.0)

**Generated:** `2026-10-25T09:18:21.140130+00:00`
**As of:** `2026-10-25T09:18:20.920341+00:00`
**Git HEAD:** `65dcabededad8a49b667115d3f1642ee62d6901c`
**Window:** last 7 days
**Total ledger rows:** `18242`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.2% | 37/18242 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18242 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18242 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 17967 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 175 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 100 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18242 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 17967 |
| `crypto-breakdown` | 175 |
| `crypto-oversold-bounce` | 100 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18242 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18180 |
| `BLOCK` | 37 |
| `ALERT_ONLY` | 25 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18242 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18242 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18180 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
