# Gate Distribution Status (v3.24.0)

**Generated:** `2026-06-15T11:12:51.755227+00:00`
**As of:** `2026-06-15T11:12:51.590544+00:00`
**Git HEAD:** `4bd7ed2403e09608047d5f442da72e500a5885f6`
**Window:** last 7 days
**Total ledger rows:** `16238`
**Shadow-eligible rows:** `0`

## Why `shadow_eligible_count = 0`

| Factor | Share % | Explanation |
|---|---|---|
| `confidence_decision=NULL` | 100.0% | confidence_score is NULL — emit path did not run, monitor missed back-fill, or downstream consumer did not persist the field. |
| `risk_decision=REJECT` | 64.8% | 10516/16238 rows blocked at the risk gate (REJECT) |
| `risk_decision=HALTED_BY_DRAWDOWN_GUARD` | 1.0% | 169/16238 rows blocked at the risk gate (HALTED_BY_DRAWDOWN_GUARD) |
| `risk_decision=NO_SIGNAL` | 33.4% | 5424/16238 rows blocked at the risk gate (NO_SIGNAL) |

## Top 3 blockers overall

| Blocker | Count |
|---|---|
| `predator_bracket` | 10334 |
| `no_setup` | 5424 |
| `NO_BLOCKER` | 129 |

## Top blocker per monitor

| Monitor | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-monitor` | `predator_bracket` | 10334 | 63.6% |

## Top blocker per strategy

| Strategy | Top blocker | Count | Share |
|---|---|---|---|
| `crypto-momentum` | `predator_bracket` | 10334 | 64.3% |
| `crypto-breakdown` | `short_disabled` | 86 | 100.0% |
| `crypto-oversold-bounce` | `NO_BLOCKER` | 35 | 50.0% |

## Rows by monitor

| Monitor | Count |
|---|---|
| `crypto-monitor` | 16238 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 16082 |
| `crypto-breakdown` | 86 |
| `crypto-oversold-bounce` | 70 |

## Rows by risk_decision

| Risk decision | Count |
|---|---|
| `REJECT` | 10516 |
| `NO_SIGNAL` | 5424 |
| `HALTED_BY_DRAWDOWN_GUARD` | 169 |
| `DETECTED` | 97 |
| `UNKNOWN` | 32 |

## Rows by confidence_decision

| Confidence decision | Count |
|---|---|
| `NULL` | 16238 |

## Rows by gate blocker

| Gate blocker | Count |
|---|---|
| `predator_bracket` | 10334 |
| `no_setup` | 5424 |
| `NO_BLOCKER` | 129 |
| `short_disabled` | 86 |
| `alt_cap` | 61 |
| `alpaca_reject_or_deferred` | 35 |
| `daily_drawdown_guard:daily P&L -3.89% <= -3.0% -> HALT new entries` | 22 |
| `daily_drawdown_guard:daily P&L -3.88% <= -3.0% -> HALT new entries` | 18 |
| `daily_drawdown_guard:daily P&L -3.80% <= -3.0% -> HALT new entries` | 14 |
| `daily_drawdown_guard:daily P&L -3.77% <= -3.0% -> HALT new entries` | 14 |
| `daily_drawdown_guard:daily P&L -3.71% <= -3.0% -> HALT new entries` | 14 |
| `daily_drawdown_guard:daily P&L -3.91% <= -3.0% -> HALT new entries` | 12 |
| `daily_drawdown_guard:daily P&L -3.94% <= -3.0% -> HALT new entries` | 12 |
| `daily_drawdown_guard:daily P&L -3.76% <= -3.0% -> HALT new entries` | 10 |
| `daily_drawdown_guard:daily P&L -3.73% <= -3.0% -> HALT new entries` | 8 |
| `daily_drawdown_guard:daily P&L -3.75% <= -3.0% -> HALT new entries` | 8 |
| `daily_drawdown_guard:daily P&L -3.92% <= -3.0% -> HALT new entries` | 8 |
| `daily_drawdown_guard:daily P&L -3.81% <= -3.0% -> HALT new entries` | 8 |
| `daily_drawdown_guard:daily P&L -3.72% <= -3.0% -> HALT new entries` | 6 |
| `daily_drawdown_guard:daily P&L -3.86% <= -3.0% -> HALT new entries` | 4 |
| `daily_drawdown_guard:daily P&L -3.82% <= -3.0% -> HALT new entries` | 4 |
| `daily_drawdown_guard:daily P&L -3.90% <= -3.0% -> HALT new entries` | 2 |
| `daily_drawdown_guard:daily P&L -3.74% <= -3.0% -> HALT new entries` | 2 |
| `daily_drawdown_guard:daily P&L -3.83% <= -3.0% -> HALT new entries` | 2 |
| `drawdown_halt` | 1 |

## Rows by data-failure token

| Token | Count |
|---|---|
| (none) | 0 |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `GATE_DISTRIBUTION_IS_READ_ONLY`
