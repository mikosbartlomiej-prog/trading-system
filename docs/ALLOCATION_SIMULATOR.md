# Allocation Simulator — v3.19.0 (2026-06-04)

**Status:** Paper analysis layer. Not in critical trading path. Cannot
change risk limits.

## What this module is for

After the system has accumulated paper trades, the operator wants to ask:
*"What would the portfolio look like under different ways of allocating
capital across enabled strategies?"*

`shared/allocation_simulator.py` provides a deterministic, fail-soft
simulation across six different allocation modes. The results are
informational; the **risk engine retains final say on every order**.

## Hard guarantees

- **Paper analysis only.** No broker calls. No state.json writes. No
  risk-limit changes. No position-size increases.
- **PURE function.** `simulate_allocation(mode, per_strategy_paper_metrics)`
  reads only the dict passed in.
- **Fail-soft.** Missing inputs → mode skipped with a note (never crash).
- **No leverage assumptions.** Capital is a hypothetical accounting unit
  (default `$100,000`) mirroring paper. Weights are fractions of capital.
- **Never auto-allocates real capital.** The output is a report.

## The six modes

| Mode                  | Idea                                                  |
|-----------------------|-------------------------------------------------------|
| `equal_weight`        | 1/N across eligible strategies                        |
| `confidence_weighted` | Weighted by profit factor                             |
| `risk_adjusted`       | PF / max_drawdown (penalises high-DD strategies)      |
| `drawdown_capped`     | Equal weight; skip PF<1 or max_dd > drawdown_cap_pct  |
| `regime_aware`        | Boost strategies favouring `current_regime`           |
| `top_n`               | Equal weight across top-N by composite score          |

A strategy is **eligible** if `n_closed >= 1` in the metrics dict.
Disabled strategies (via `disabled_strategies` kwarg) are filtered first.

## Output shape (per mode)

```json
{
  "mode":                      "equal_weight",
  "capital_usd":               100000.0,
  "current_regime":            "NEUTRAL",
  "weights":                   {"momentum-long": 0.5, "geo-defense": 0.5},
  "exposure_by_strategy":      {"momentum-long": 0.5, "geo-defense": 0.5},
  "exposure_by_symbol":        {"AAPL": 0.3, "RTX": 0.4},
  "exposure_by_regime":        {"NEUTRAL": 0.7, "RISK_ON": 0.3},
  "total_paper_pnl_usd":       1234.56,
  "max_paper_drawdown_pct":    0.08,
  "volatility_proxy":          12.34,
  "profit_factor":             1.45,
  "expectancy":                0.005,
  "worst_day_pnl":             -120.0,
  "worst_streak_losses":       4,
  "correlation_proxy":         0.32,
  "notes":                     "paper_analysis_only"
}
```

## CLI

```bash
# Read default 180d window, all enabled strategies, default $100k.
python3 scripts/allocation_simulation_report.py

# Customise window + regime
python3 scripts/allocation_simulation_report.py \
    --window-days 90 \
    --current-regime RISK_ON \
    --top-n 7

# Stdout-only
python3 scripts/allocation_simulation_report.py --dry-run
```

Reports land at `docs/allocation_simulation_LATEST.{md,json}`.

## Audit trail

`generate_allocation_report` emits ONE JSONL line per run:

```json
{
  "type":         "allocation_simulation",
  "source":       "evidence_analysis",
  "decision":     "ANALYSED",
  "modes":        ["equal_weight", "confidence_weighted", ...],
  "best_by_pnl":  "risk_adjusted",
  "best_by_pf":   "drawdown_capped",
  "best_by_dd":   "drawdown_capped",
  "decided_at":   "2026-06-04T13:42:01Z"
}
```

## What this CANNOT do (by construction)

- Cannot raise `max_correlated_bucket_pct` or any risk-config value.
- Cannot place orders.
- Cannot mutate `state.json` or `runtime_state.json`.
- Cannot enable a strategy that is `DISABLED` or
  `OBSERVE_ONLY` in `shared/strategy_quality_gate.py`.
- Cannot bypass the risk engine — the operator manually decides whether
  to adjust strategy weights, and the order path still runs through
  `risk_officer.evaluate_trade`.

## Re-decision triggers (when operator should re-read the report)

- After a meaningful drawdown.
- After the LLM Senior PM proposes a re-allocation.
- After a regime transition.
- Before flipping `EDGE_GATE_ENABLED` (combined with
  `docs/edge_evidence_LATEST.md`).

## Related files

- `shared/allocation_simulator.py` — implementation.
- `shared/paper_experiment.py` — paper-trade ledger source of truth.
- `scripts/allocation_simulation_report.py` — CLI.
- `tests/test_allocation_simulator_v3190.py` — unit tests.
