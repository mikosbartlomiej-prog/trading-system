# Intraday Profit Protection — v3.5 (2026-05-14)

**Status:** LIVE
**Module:** `shared/intraday_governor.py`
**Persistence:** `learning-loop/runtime_state.json` (separate from `state.json`)
**Source of truth (config):** `config/aggressive_profile.json` →
`intraday_profit_protection` + `profit_floor` + `intraday_exposure_reduction`
**Audit:** `journal/autonomy/YYYY-MM-DD.jsonl`

---

## Problem this solves

A day that hits `+$5,000` intraday cannot end `-$2,000` without
deterministic action firing first.

The v3.3 `peak_tracker` (added 2026-05-13 after the 2026-05-12 disaster)
had three flaws that this iteration repairs:

| v3.3 flaw                          | v3.5 fix                                                                                  |
|---|---|
| State stored in `state.json`, which 5-min monitors are no longer allowed to commit (rule C). Writes silently disappeared. | State lives in `learning-loop/runtime_state.json`, custodied by exit-monitor with `contents: write` + a tiny post-step `git push` of that one file. |
| Only 3 states (NORMAL / WARN / PROFIT_LOCK). No DEFEND_DAY tier, no green-to-red protection, no profit floor. | 7-state FSM: FLAT → GREEN → STRONG_GREEN → GIVEBACK_WARN → PROFIT_LOCK → DEFEND_DAY → RED_DAY_AFTER_GREEN. |
| Only emitted email + harvested winning options. Did **not** block new entries, did **not** clamp gross exposure, did **not** track per-position MFE. | Each state has a deterministic action bundle: gross-exposure cap, options-first reduction, entry block, profit floor, position-level MFE harvest. |

---

## State machine

```
NEW_DAY ─ (any update) ─► FLAT ──── (cur > $500) ───► GREEN
                                                         │
                                          (peak ≥ $3k OR ≥ 3% equity)
                                                         ▼
                                                  STRONG_GREEN
                                                         │
                                              (retrace ≥ 25%)
                                                         ▼
                                                  GIVEBACK_WARN
                                                         │
                                              (retrace ≥ 35%)
                                                         ▼
                                                  PROFIT_LOCK
                                                         │
                                              (retrace ≥ 50%)
                                                         ▼
                                                  DEFEND_DAY
                                                         │
                                  (retrace ≥ 60%  OR  cur ≤ 0 after peak ≥ $1k
                                   OR  peak ≥ $5k AND cur ≤ $2k AND retrace ≥ 60%)
                                                         ▼
                                                RED_DAY_AFTER_GREEN
```

**Ratchet rule:** Once today's FSM lands in PROFIT_LOCK, DEFEND_DAY or
RED_DAY_AFTER_GREEN it never downgrades. A bounce back to +$3k after a
visit to DEFEND_DAY stays in DEFEND_DAY. The state resets at UTC midnight.

---

## Per-state action bundle

Each state maps to a deterministic action set. The numbers below are the
defaults in `config/aggressive_profile.json`; operators can tune per profile.

| State                  | max gross | block entries                                | options first | profit floor | exit-monitor action                                                  |
|---|---|---|---|---|---|
| `FLAT` / `GREEN`       | 1.50      | no                                           | no            | no           | normal heuristics                                                    |
| `STRONG_GREEN`         | 1.50      | no                                           | no            | yes (tiered) | normal heuristics                                                    |
| `GIVEBACK_WARN`        | 1.25      | no                                           | no            | yes          | tighten trailing; harvest if position MFE crossed threshold          |
| `PROFIT_LOCK`          | 1.00      | yes, unless score ≥ 0.65                     | **yes**       | yes          | harvest every winner ≥+8% and **all** options; MARKET sells          |
| `DEFEND_DAY`           | 0.50      | **yes**                                      | **yes**       | yes          | close all options; harvest winners ≥+5%; flatten weak positions      |
| `RED_DAY_AFTER_GREEN`  | 0.25      | **yes, until next session**                  | **yes**       | yes          | close every intraday position; keep only explicit hedges             |

---

## Profit floor

Once intraday peak crosses a tier, `floor = peak × lock_ratio`.

| Peak                  | Lock ratio | Example floor                |
|---|---|---|
| ≥ $1,000              | 0.25       | peak $2k → floor $500        |
| ≥ $3,000              | 0.40       | peak $4k → floor $1,600      |
| ≥ $5,000              | 0.50       | peak $6k → floor $3,000      |

A `+$5k` day MUST end no worse than `+$2.5k` or the system has failed
its own contract — that's what RED_DAY_AFTER_GREEN exists to enforce.

---

## Position-level MFE harvest

In parallel with the portfolio-level FSM, each open position tracks its
own Max Favorable Excursion (peak P&L percent vs entry). Rules:

| Position peak | Retrace from peak | Action      |
|---|---|---|
| ≥ +20%        | ≥ 25%             | HARVEST 100%|
| ≥ +12%        | ≥ 35%             | REDUCE 75%  |
| ≥ +8%         | ≥ 40%             | REDUCE 50%  |
| else          |                   | HOLD        |

MFE state is persisted in `runtime_state.json::position_mfe`.

---

## Persistence contract (the architectural fix)

Two files, two purposes, two writers:

```
learning-loop/state.json
  → DAILY adapter snapshot
  → written by daily-learning, weekly-retro, manual-maintenance (RARE)
  → shared.state_policy.ALLOWED_ACTORS gates it
  → committed once per day

learning-loop/runtime_state.json
  → CRON-SCOPED runtime snapshot (intraday governor + position MFE + option trailing)
  → written by exit-monitor / options-exit-monitor (every 5 min during session)
  → shared.state_policy.RUNTIME_STATE_ACTORS gates it
  → committed via a single-file `git push` step in the workflow YAML
```

Monitor workflows that update runtime_state.json:

  - `STATE_WRITE_ACTOR=intraday-monitor` (or `options-exit-monitor`)
  - `permissions: contents: write`
  - Post-step `git add learning-loop/runtime_state.json && git push`

Other monitors **read** runtime_state.json (via `shared.runtime_state.
read_section`) without needing write permission.

---

## Wiring map

| Where                                  | Calls                                                            |
|---|---|
| `exit-monitor/monitor.py::run_exit_check`    | `intraday_governor.update(account)` once per tick, sends `notify_intraday_state` per FSM transition |
| `exit-monitor/monitor.py::enrich_position`   | reads `get_snapshot()` + `position_mfe_action(pos)` to elevate position rec to `PROFIT_LOCK` (which routes to `place_emergency_close` MARKET-DELETE path) |
| `options-exit-monitor/monitor.py::evaluate`  | `_intraday_governor_decision(pos, pl_pct)` injects a `GOVERNOR` decision tag ahead of NEARDTH/TP/SL; MARKET sells tagged `exit-governor-*` |
| `shared/alpaca_orders.py::place_stock_bracket` | `_intraday_governor_gate(symbol, side, size, asset_class)` before risk-officer; rejects entries during DEFEND_DAY / RED_DAY_AFTER_GREEN |
| `shared/alpaca_orders.py::place_crypto_order`  | same gate (also runs 24/7 so weekend crypto can't rebuild what we just shed) |
| `shared/alpaca_orders.py::place_simple_buy`    | same gate with **score** kwarg — high-score signals (≥ 0.65) override PROFIT_LOCK block; DEFEND_DAY/RED blocks are absolute |
| `shared/notify.py::notify_intraday_state`      | emails `[INTRADAY-DEFEND]` / `[INTRADAY-RED-AFTER-GREEN]` / etc; dedup per UTC day in `runtime_state.alerts_sent` |
| `shared/audit.py::write_audit_event`           | every FSM transition + every gate block writes one JSONL line under `journal/autonomy/YYYY-MM-DD.jsonl` |

---

## Audit event types

Written by `intraday_governor.emit_audit` to `journal/autonomy/YYYY-MM-DD.jsonl`.

```
UPDATE_INTRADAY_PEAK              transition into non-protected state
GIVEBACK_WARN                     entered GIVEBACK_WARN
PROFIT_LOCK_TRIGGERED             entered PROFIT_LOCK
DEFEND_DAY_TRIGGERED              entered DEFEND_DAY
RED_DAY_AFTER_GREEN_PROTECTION    entered RED_DAY_AFTER_GREEN
BLOCK_NEW_ENTRIES_INTRADAY        alpaca_orders gate rejected an entry
TIGHTEN_STOPS_INTRADAY            (reserved for trailing tightening)
REDUCE_GROSS_EXPOSURE_INTRADAY    (emitted by portfolio_risk after clamp)
POSITION_MFE_TRAIL_REDUCE         per-position MFE reduce fired
POSITION_MFE_TRAIL_EXIT           per-position MFE harvest fired (full close)
INTRADAY_TREND_REVERSAL_EXIT      (reserved for VWAP/ORH module — P2)
```

Every record carries:

```
timestamp, event_type, actor, session_start_equity, current_equity,
intraday_peak_equity, intraday_peak_pnl, current_intraday_pnl,
giveback_usd, giveback_pct_of_peak, profit_floor_usd, max_gross_target,
state_before, state_after, action, reason, affected_symbols
```

---

## Test coverage

| File                                            | Cases | Covers                                                                                  |
|---|---|---|
| `tests/test_intraday_governor.py`               | 23    | +5000 → -2000 full cascade, green-to-red, profit floor (3 tiers), MFE harvest tiers, account-unavailable block, entry gate, max-gross ratchet, audit transition, legacy peak_tracker shim |
| `tests/test_intraday_governor_integration.py`   | 6     | alpaca_orders gate: stock blocked in DEFEND_DAY, crypto blocked in RED, options blocked in PROFIT_LOCK without score, options allowed with score≥0.65, stock allowed in GREEN, account-unavailable blocks. (Skips on Python 3.9 — CI on 3.11.) |
| `tests/test_peak_tracker.py`                    | 9     | Legacy shim verdict mapping; existing scenarios re-tuned for v3.5 thresholds (25/35/50/60). |

Run locally:

```bash
python -m unittest tests.test_intraday_governor \
                   tests.test_intraday_governor_integration \
                   tests.test_peak_tracker
```

---

## How `+$5,000 → -$2,000` is now prevented

Walk-through using the actual default config:

| Tick | Equity   | Daily PnL | Peak PnL | Retrace | State                  | Action                                                          |
|------|---------:|----------:|---------:|--------:|------------------------|-----------------------------------------------------------------|
| 1    | 102,000  | +2,000    | +2,000   |    0%   | GREEN                  | normal trading                                                  |
| 2    | 105,000  | +5,000    | +5,000   |    0%   | STRONG_GREEN           | floor armed at +$2,500                                          |
| 3    | 103,500  | +3,500    | +5,000   |   30%   | GIVEBACK_WARN          | tighten stops; new entries still allowed                        |
| 4    | 102,500  | +2,500    | +5,000   |   50%   | DEFEND_DAY             | **email** + **gross→0.5×** + **block new entries** + close all options + flatten weak |
| 5    | 101,000  | +1,000    | +5,000   |   80%   | RED_DAY_AFTER_GREEN    | **email** + **gross→0.25×** + close every intraday position (options first) |
| 6    |  98,000  | -2,000    | +5,000   | >100%   | RED_DAY_AFTER_GREEN    | (same; alerts deduped; block remains until next session)        |

The day **cannot** reach tick 6 without ticks 4 and 5 having already
flattened most of the book — that's the contract.

---

## Operator runbook

- **Check current intraday state:** `python -c "import sys; sys.path.insert(0,'shared'); from intraday_governor import get_snapshot, summarize; print(summarize())"` from the repo root.
- **Inspect audit trail:** `tail -n 20 journal/autonomy/$(date -u +%Y-%m-%d).jsonl`
- **Disable for testing only (NOT prod):** set `INTRADAY_PROTECTION_ENABLED=false` in the workflow env. Production should never disable.
- **Manual reset (after operator intervention, e.g. a flat-out):** edit `learning-loop/runtime_state.json` and clear the `intraday_governor` section. The next exit-monitor cron re-initialises.

---

## Known limitations / P2 follow-ups

- VWAP / opening-range / 5-min momentum signals (spec §6) NOT implemented; `INTRADAY_TREND_REVERSAL_EXIT` audit type reserved but never emitted. Adds another exit reason ranking ahead of NEARDTH; needs an intraday bar feed.
- Backtest harness needs new metrics: `intraday_peak_pnl_avg`, `percent_of_peak_profit_retained`, `green_to_red_count`. Currently the harness is daily-bar only — no intraday simulation yet.
- Dashboard panel for "today's giveback" not built; data already lives in runtime_state.json (`/api/snapshot` could surface it after a small extension to the worker).
- Allocator (`shared/allocator.py`) does not yet read `runtime_state.intraday_governor` to skip same-day redeploy after RED_DAY_AFTER_GREEN. Today protection is exit-side only; next-day plan from daily-learning still has the deterministic option to restore normal sizing or adapt down.
