# Position Management (v3.15.0)

**Module:** `shared/position_manager.py`
**Audit-board feedback closed:** FB-011 (no fire-and-forget)
**Status:** module shipped + tested; wiring into exit-monitor is v3.16 scope

## What it is

Per-position state machine that aggregates existing reactive exits
(SL/TP bracket, governor, safe_close, intraday_governor) and adds
**proactive** triggers:
- time-stop
- invalidation level
- exit on confidence drop
- exit on profile-quality drop
- explicit partial exit
- max adverse excursion (MAE) safety net
- trailing stop on profit retrace

It does NOT replace existing exits. It recommends an action; the
exit-monitor remains the only path to `safe_close`.

## Lifecycle states

```
INTAKE → ARMED → TRAILING (on profit) → CLOSED
                        ↘ INVALIDATING → CLOSED
                        ↘ TIME_EXPIRED → CLOSED
```

- **INTAKE** — first 5 minutes after open. Bracket settling.
- **ARMED** — standard monitoring; all triggers active.
- **TRAILING** — in profit ≥ 5%; trailing stop armed at 40% retrace.
- **INVALIDATING** — explicit invalidation signal fired; pending close.
- **TIME_EXPIRED** — time-stop hit; pending close.
- **CLOSED** — terminal.

## Recommendations (returned to exit-monitor)

| Recommendation | When |
|---|---|
| HOLD | Default; nothing triggered |
| PARTIAL_EXIT | At +10% profit (one-shot, half qty) |
| FULL_EXIT | Time stop / MAE / trailing retrace / confidence collapse / safe_mode / kill_switch |
| INVALIDATE | Explicit invalidation signal (e.g. setup thesis broken) |

## Hard priority order (highest first)

1. **kill_switch_armed** → FULL_EXIT (always wins)
2. **safe_mode_active** → FULL_EXIT (always wins)
3. **explicit invalidation** → INVALIDATE
4. **INTAKE grace** (< 5 min) → HOLD
5. **Time stop** → FULL_EXIT (TIME_EXPIRED)
6. **MAE > 8%** → FULL_EXIT (safety net)
7. **Confidence collapsed** (current < 40% AND < 60% of entry) → FULL_EXIT
8. **Profile quality collapsed** (< 30%) → FULL_EXIT
9. **Trailing retrace** (40% from peak) → FULL_EXIT
10. **Partial-exit at +10% profit** → PARTIAL_EXIT (0.5x qty)
11. else → HOLD

## What it never does

- Place orders directly (exit-monitor mediates via `safe_close`)
- Override emergency closes
- Increase position size
- Skip risk_officer

## Tunables (conservative defaults)

| Constant | Default | Why |
|---|---|---|
| `INTAKE_GRACE_MINUTES` | 5 | Bracket OCO needs to settle |
| `DEFAULT_TIME_STOP_HOURS` | 48 | Swing trade reset |
| `INTRADAY_TIME_STOP_HOURS` | 6 | Intraday positions |
| `TRAIL_ARM_PROFIT_PCT` | 0.05 | Don't trail until in profit |
| `TRAIL_RETRACE_PCT` | 0.40 | Conservative — gives room |
| `PARTIAL_EXIT_PROFIT_PCT` | 0.10 | Half-off at +10% |
| `MAX_ADVERSE_EXCURSION_PCT` | 0.08 | Safety net beyond SL |
| `CONFIDENCE_DROP_THRESHOLD` | 0.40 | Below ALLOW threshold |
| `QUALITY_DROP_THRESHOLD` | 0.30 | Data went stale |

## Why "fire-and-forget" was the previous state

The system had reactive exits but no aggregated lifecycle. Each tick the
exit-monitor evaluated current bar against bracket → emit close if SL/TP
hit. There was no:
- explicit time stop (positions could rot for weeks)
- MAE tracking beyond SL
- exit on data quality drop
- partial exit policy

`position_manager` adds these as deterministic rules.

## Wiring (v3.16 scope)

- Persist `PositionState` per symbol in `learning-loop/runtime_state.json::positions`.
- `exit-monitor.run_exit_check()` calls `evaluate_position(state)` per position.
- On `PARTIAL_EXIT`: `safe_close(symbol, intent_qty=current_qty * 0.5)`.
- On `FULL_EXIT`: `safe_close(symbol, intent_qty=current_qty)`.
- Audit emit `LIFECYCLE_TRANSITION` event.

## Tests

`tests/test_feedback_v3150.py::TestPositionManager` — 9 tests covering
all priority rules.
