# Gate Distribution Status (v3.24.0)

**Generated:** `2026-06-25T08:00:14.409426+00:00`
**As of:** `2026-06-25T08:00:14.176114+00:00`
**Git HEAD:** `82faa5a91dc819aa0a0478773d18c63c45007b56`
**Window:** last 7 days
**Total ledger rows:** `18697`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.3% | 61/18697 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18697 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18697 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18407 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 194 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 96 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18697 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18407 |
| `crypto-oversold-bounce` | 194 |
| `crypto-breakdown` | 96 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18697 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18576 |
| `BLOCK` | 61 |
| `ALERT_ONLY` | 60 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18697 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18697 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18576 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
