# Session Effectiveness Monitor (v3.15.0)

**Module:** `shared/session_effectiveness.py`
**Audit-board feedback closed:** FB-013 (real-time effectiveness verification)
**Status:** shipped, tests green

## What it is

Append-only JSONL event stream + report aggregator. Lets the system answer
"how effective is the pipeline RIGHT NOW?" during a live session.

Pre-v3.15.0 the system had `scripts/session_report.py` which is post-session.
This module is in-session: it can trigger safe_mode if effectiveness drops.

## Events tracked

| Event | When emitted |
|---|---|
| `signal_emitted` | Monitor decided to send a BUY/SELL signal |
| `signal_rejected_by_confidence` | confidence < threshold |
| `signal_rejected_by_risk_engine` | risk_officer rejected |
| `signal_rejected_by_liquidity_guard` | sweep guard BLOCKED |
| `signal_rejected_by_source_tier` | Tier 3 ineligible |
| `position_opened` | safe_close / place_*_order succeeded |
| `position_closed_winner` | exit at P&L > 0 |
| `position_closed_loser` | exit at P&L ≤ 0 |
| `confidence_calibration_sample` | (confidence_at_entry, outcome) tuple |

## Storage

`learning-loop/session_metrics/<date>.jsonl`. Append-only. Lines parseable
in isolation. Fail-soft: write error → silent skip (never blocks monitor).

## Report

`SessionEffectivenessReport`:
- `signals_emitted`
- `rejection_breakdown` per gate
- `positions_opened` / `closed_winners` / `closed_losers`
- `hit_rate` (winners / closed)
- `avg_mae_pct`, `avg_mfe_pct`
- `confidence_calibration` (low/mid/high confidence → hit rate)
- `degradation_signals` (list)
- `recommend_safe_mode` (bool)

## Degradation rules (trigger safe_mode recommendation)

| Signal | Condition |
|---|---|
| `low_hit_rate` | closed ≥ 10 AND hit_rate < 30% |
| `adverse_excursion_dominant` | avg_mae > 5% AND mae/mfe > 1.5 |
| `pipeline_choked` | decisions ≥ 10 AND rejection_rate > 95% |
| `confidence_calibration_inverted` | high-conf hit_rate < low-conf hit_rate - 20% |

≥ 2 degradation signals → `recommend_safe_mode = True`.

## What it does NOT do

- Open trades
- Change strategies
- Raise confidence
- Increase position size
- Override risk engine

It is **strictly defensive**: it can only RECOMMEND tighter behavior.

## Wiring (v3.16 scope)

- Each monitor calls `record_event(EVT_SIGNAL_EMITTED, symbol, payload)`
  after a signal decision.
- Each rejection gate calls the matching `EVT_REJECTED_*`.
- `exit-monitor` calls `EVT_POSITION_CLOSED_WINNER/LOSER` on close.
- A new workflow `session-effectiveness-check.yml` runs `report_today()`
  every 15 minutes; if `recommend_safe_mode`, calls
  `safe_mode.maybe_enter(reason="effectiveness_degradation")`.

## Cost

$0/month. JSONL files in repo. No DB.

## Tests

`tests/test_feedback_v3150.py::TestSessionEffectivenessMonitor` — 4 tests:
- record + load
- invalid event type silently ignored
- low hit rate triggers degradation
- recommend_safe_mode logic

## Future

- Per-strategy effectiveness slicing
- Per-symbol effectiveness (which symbols actually profit)
- Cross-session decay detection (this week vs last week)
