# Exit Quality (v3.20 ETAP 8)

Read-only post-mortem analysis of closed paper / shadow trades. Lives in
`shared/exit_quality.py` and is exposed via
`scripts/exit_quality_report.py`.

## Why

The audit board (2026-06-02) reaffirmed `NOT_SAFE_FOR_LIVE_TRADING`.
One open follow-up is that the system has no honest, deterministic
picture of *how* its closed trades actually exited:

* Did winners surrender most of their peak before we closed them?
* Did stops fire at the planned price, or did they overshoot on gaps?
* In which regime / confidence bucket did the exits behave worst?
* Would a simple trailing-stop rule have helped, even synthetically?

The Exit Quality module answers these questions by reading the existing
paper / backtest / replay JSONL ledger and producing a deterministic
dict + Markdown report. **It never mutates state.** It never flips
`EDGE_GATE_ENABLED`. It never enables live trading. It NEVER calls the
broker or any paid API. Recommendations in the report are strings —
topics for the operator to review.

## Contract

* Pure functions. Same input ledger → same output dict.
* Fail-soft on every code path. Bad data is coerced or dropped; the
  module never raises.
* Evidence boundary preserved (see `shared/evidence_source.py`). PAPER,
  BACKTEST, REPLAY each live in their own directory. The module refuses
  to mix them in a single aggregate.
* No paid APIs, no live broker calls. Free operation.
* Output is `dict + report + recommendations[]`. **No runtime
  mutation.**

## Per-trade fields

`analyse_trade(record)` computes:

| Field | Meaning |
|---|---|
| `mfe` / `mae` | Maximum favourable / adverse excursion in price units (per side). |
| `mfe_pct` / `mae_pct` | Same as fractions of the entry price. |
| `profit_giveback_usd` / `profit_giveback_pct` | How many dollars of the MFE peak were surrendered before exit, and the same as a share of the peak. |
| `stop_efficiency` | Losing trades only. `actual_loss / planned_sl_loss`. 1.0 = stop fired exactly; <1.0 = better than SL; >1.0 = worse than SL (gap or slippage). |
| `target_efficiency` | Winning trades only. `actual_profit / planned_tp_profit`. 1.0 = TP exactly; <1.0 = stopped short of TP; >1.0 = beyond TP. |
| `exit_too_early` | True iff the trade closed positive AND giveback ≥ 20 % of peak. |
| `exit_too_late` | True iff the trade closed negative AND actual loss exceeds the planned SL by > 25 %. |
| `time_in_trade_minutes` | `closed_at − opened_at`. 0 if either field missing. |
| `trailing_stop_candidate` | Synthetic check: would an 8 % trail off the MFE peak (with 12 h min-hold) have produced a better net dollar outcome? True / False / None. |
| `regime_at_entry` | Mirror of the source record. |
| `confidence_bucket_at_entry` | low (<0.50) / mid (<0.70) / high (≥0.70) / unknown. |

### Why these thresholds

| Constant | Value | Source |
|---|---|---|
| `EARLY_EXIT_GIVEBACK_THRESHOLD` | 0.20 | Mirrors the early-exit detection used in `learning-loop/heuristic_proposals.md` (an LLM proposal from 2026-05-07 first flagged early TPs). |
| `LATE_EXIT_OVERSHOOT_THRESHOLD` | 0.25 | Matches the 25 % overshoot rule used implicitly by `incident_pattern_detector.py::p14_pdt_block_cascade` and operator briefs. |
| `TRAILING_STOP_TRAIL_PCT` | 0.08 | Same 8 % trail v3.3 uses in `options-exit-monitor` and `peak_tracker`. |
| `TRAILING_STOP_MIN_HOLD_MIN` | 720 (12 h) | Same 12 h min-hold v3.3 uses for trailing decisions. |
| `MIN_BUCKET_N_FOR_RECO` | 5 | Refuses to emit a review recommendation on n < 5 — too small to be honest. |

## Aggregations

`analyse_ledger(window_days=180, source=PAPER)` returns:

```text
{
  "window_days":           int,
  "source":                "PAPER" | "BACKTEST" | "REPLAY",
  "trades":                [ per_trade_dict, ... ],
  "per_strategy":          { strategy: aggregate, ... },
  "per_symbol":            { symbol:   aggregate, ... },
  "per_regime":            { regime:   aggregate, ... },
  "per_confidence_bucket": { bucket:   aggregate, ... },
  "overall":               aggregate,
  "recommendations":       [ str, ... ],
}
```

Each `aggregate` reports:

* `n`, `wins`, `losses`, `win_rate`
* `avg_mfe_pct`, `avg_mae_pct`, `avg_giveback_pct`
* `mean_stop_efficiency`, `mean_target_efficiency`
* `share_exit_too_early`, `share_exit_too_late`,
  `share_trailing_helps`
* `avg_time_in_trade_minutes`

## Recommendations

Strings only, generated deterministically when a bucket has at least
`MIN_BUCKET_N_FOR_RECO` trades and crosses one of:

| Condition | Wording |
|---|---|
| `share_exit_too_early ≥ 0.30` | "Topic for review: TP placement / partial-take rule. Does not enable live trading." |
| `share_exit_too_late ≥ 0.20` | "Topic for review: stop placement / gap protection. Does not enable live trading." |
| `share_trailing_helps ≥ 0.40` | "Topic for review: trailing rule." |
| `mean_stop_efficiency ≥ 1.20` | "Topic for review: gap / slippage assumptions." |
| `mean_target_efficiency ≤ 0.50` | "Topic for review: TP placement vs realistic targets." |

The wording deliberately ends every recommendation with "Does not enable
live trading." so that any downstream consumer that grep-collects these
strings cannot accidentally interpret them as a green light.

## Usage

```bash
# Default (PAPER ledger, 180 day window) → writes docs/exit_quality_LATEST.md
python3 scripts/exit_quality_report.py

# Backtest ledger triage → writes docs/exit_quality_BACKTEST_LATEST.md
python3 scripts/exit_quality_report.py --source backtest

# Smaller window
python3 scripts/exit_quality_report.py --window-days 30

# Pipe the result dict as JSON
python3 scripts/exit_quality_report.py --json
```

The script exits 0 even when the ledger is empty — that means nothing
has been recorded yet, which is not a failure.

## What this module is NOT

* It is NOT an automatic strategy tuner.
* It does NOT mutate `learning-loop/state.json`.
* It does NOT mutate `learning-loop/runtime_state.json`.
* It does NOT touch the broker, paid feeds, or any external service.
* It does NOT auto-enable or auto-disable any strategy.
* It NEVER recommends live trading; it can only flag review topics.

## Tests

`tests/test_exit_quality_v3200.py` covers:

* MFE / MAE from explicit price series (long + short).
* Profit giveback flagging (positive case + negative case).
* Stop efficiency math (exact, overshoot, missing planned SL).
* Per-regime breakdown.
* Per-confidence-bucket breakdown.
* Recommendations generated; no runtime mutation (snapshot of repo
  state files before / after).
* Evidence boundary respected (BACKTEST never leaks into PAPER).
* Trailing-stop simulation min-hold rule.
* Empty ledger + malformed record fail-soft.

Run with:

```bash
python3 -m unittest tests.test_exit_quality_v3200
```
