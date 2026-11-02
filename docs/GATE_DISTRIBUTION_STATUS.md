# Gate Distribution Status (v3.24.0)

**Generated:** `2026-11-02T12:47:01.289525+00:00`
**As of:** `2026-11-02T12:47:01.071147+00:00`
**Git HEAD:** `a83878a2a5a5051818490268bcfb7a66304a1f8f`
**Window:** last 7 days
**Total ledger rows:** `18612`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=BLOCK` | 0.7% | 131/18612 rows blocked at the confidence gate (BLOCK) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `NO_BLOCKER` | 18612 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `NO_BLOCKER` | 18612 | 100.0% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `NO_BLOCKER` | 18082 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 286 | 100.0% |
| `crypto-breakdown` | `NO_BLOCKER` | 244 | 100.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 18612 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 18082 |
| `crypto-oversold-bounce` | 286 |
| `crypto-breakdown` | 244 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `UNKNOWN` | 18612 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `OBSERVE_ONLY_SKIP` | 18446 |
| `BLOCK` | 131 |
| `ALERT_ONLY` | 35 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `NO_BLOCKER` | 18612 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Shadow eligibility distribution

| Bucket | Count |
|---|---|
| `risk_blocked` | 18612 |

## Actionable next-fix advice

| Priority | Hint |
|---|---|
| `P2` | 18446 OBSERVE_ONLY_SKIP rows present. Verify v3.24 confidence emitter promotes top-level fields (or extend readers to consume raw_signal.* sentinels). |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
