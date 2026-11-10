# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-10T12:53:47.379018+00:00`
**As of:** `2026-11-10T12:53:47.155211+00:00`
**Git HEAD:** `cb9ddec0b656ff24f8b3a74e11ea4e28abdceca2`
**Window:** last 7 days
**Total ledger rows:** `18732`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.6% | 111/18732 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18732 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18732 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18174 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 394 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 164 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18732 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18174 |
| `crypto-oversold-bounce` | 394 |
| `crypto-breakdown` | 164 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18732 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18517 |
| `BLOCK` | 111 |
| `ALERT_ONLY` | 104 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18732 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18732 |

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
