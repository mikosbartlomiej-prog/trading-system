# Gate Distribution Status (v3.24.0)

**Generated:** `2026-09-29T10:51:14.699800+00:00`
**As of:** `2026-09-29T10:51:14.441737+00:00`
**Git HEAD:** `04107ea9d990ff8d35cc0c5cfd9e0002db825c1d`
**Window:** last 7 days
**Total ledger rows:** `18707`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.4% | 81/18707 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18707 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18707 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18362 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 310 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 35 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18707 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18362 |
| `crypto-oversold-bounce` | 310 |
| `crypto-breakdown` | 35 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18707 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18529 |
| `ALERT_ONLY` | 97 |
| `BLOCK` | 81 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18707 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18707 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18529 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
