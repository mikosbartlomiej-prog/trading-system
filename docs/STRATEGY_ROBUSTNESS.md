# Strategy Robustness Sandbox

**Version:** v3.20.0 (2026-06-04)
**Module:** `shared/strategy_robustness.py`
**Report script:** `scripts/strategy_robustness_report.py`
**Status:** sandbox-only; `SANDBOX_NEVER_OPTIMIZES = True`;
`SANDBOX_NEVER_MUTATES_RUNTIME = True`.

## Why

A point-estimate edge view (mean WR, mean PF) tells us nothing about
*fragility*. The 2026-06-02 audit board's STRAT-003 follow-up asks the
system to answer:

* Does this strategy survive ±10% / ±20% parameter shifts?
* Does it survive realistic slippage / spread sensitivity?
* Does it hold up across distinct time windows / regimes / symbols?
* Is the result dominated by a single trade / day / symbol?

The robustness sandbox answers those questions in a deterministic,
offline, paper-only environment.

## Operations performed

| Axis | Method |
| --- | --- |
| Parameter sweep | `±10%` and `±20%` perturbation per parameter key. |
| Slippage sensitivity | 0 / 2 / 5 / 10 bps. |
| Spread sensitivity | 0 / 1 / 3 / 7 bps. |
| Time-window split | Ledger split into `splits` contiguous windows. |
| Regime split | Per-regime expectancy + worst regime degradation. |
| Symbol split | Per-symbol expectancy + worst symbol degradation. |
| Drop-one best trade | Remove the single biggest winner. |
| Drop-one best day | Remove the single best trading day by net PnL. |
| Drop-one best symbol | Remove the single best-performing symbol. |

## Output shape

`run_robustness_suite(strategy, ledger, *, params, simulator) -> dict`

| Key | Type | Meaning |
| --- | --- | --- |
| `robustness_score` | float `[0, 1]` | `1.0 - max_relative_degradation`. |
| `fragility_warnings` | list of strings | One per axis where degradation exceeded its threshold. |
| `parameter_sensitivity` | dict | Per-parameter `{baseline, sensitivity, max_relative_drop, fragility_detected, variants}`. |
| `cost_sensitivity` | dict | Slippage + spread expectancy by bps. |
| `time_window_splits` / `regime_splits` / `symbol_splits` | dict | Per-bucket expectancy + worst drop. |
| `drop_one_best_trade` / `drop_one_best_day` / `drop_one_best_symbol` | dict | Baseline vs after-drop expectancy + share-of-positive-PnL. |
| `overfit_suspicion` | bool | One trade > 50% of positive PnL. |
| `dependency_on_one_symbol` | bool | One symbol > 70% of positive PnL. |
| `dependency_on_one_day` | bool | One day > 70% of positive PnL. |
| `dependency_on_one_regime` | bool | One regime > 70% of positive PnL. |
| `sandbox_never_optimizes` | bool | Echo of `SANDBOX_NEVER_OPTIMIZES`. |
| `sandbox_never_mutates_runtime` | bool | Echo of `SANDBOX_NEVER_MUTATES_RUNTIME`. |

## Determinism

Every sweep is deterministic. The same paper ledger always produces the
same `robustness_score` and the same `fragility_warnings`. The default
simulator is a pure function with no random state — it only subtracts a
proportional cost based on the supplied slippage + spread bps.

Callers may inject a custom `simulator(ledger, *, params, slippage_bps,
spread_bps) -> list[dict]` if they have a deterministic historical
replayer. The sandbox treats it as opaque and verifies on every run
that the input ledger was not mutated.

## What this does NOT do

* It does not place trades.
* It does not adjust strategy parameters in the runtime — it only
  reports what would happen under hypothetical perturbations.
* It does not change risk limits.
* It does not bypass safe-mode / kill-switch / audit log.
* It does not call paid APIs.
* It does not mix BACKTEST/REPLAY/PAPER evidence — the report script
  consumes paper records only.
* It does not flip `EDGE_GATE_ENABLED`.
* It does not recommend live trading.

## Usage

```bash
python3 scripts/strategy_robustness_report.py
python3 scripts/strategy_robustness_report.py --window-days 90
python3 scripts/strategy_robustness_report.py --json
```

Output: `docs/STRATEGY_ROBUSTNESS_LATEST.md` (plus sibling `.json` when
`--json` is passed).

## Fragility thresholds (defaults)

| Constant | Default |
| --- | --- |
| `DEGRADATION_FRAGILITY_THRESHOLD` | 0.30 |
| `SLIPPAGE_FRAGILITY_THRESHOLD` | 0.40 |
| `SPREAD_FRAGILITY_THRESHOLD` | 0.40 |
| `TIME_SPLIT_FRAGILITY_THRESHOLD` | 0.50 |
| `REGIME_SPLIT_FRAGILITY_THRESHOLD` | 0.50 |
| `SYMBOL_SPLIT_FRAGILITY_THRESHOLD` | 0.50 |
| `OVERFIT_SUSPICION_PCT` | 0.50 (one trade > 50% of positive PnL) |
| `SINGLE_SYMBOL_DEPENDENCE_PCT` | 0.70 |
| `SINGLE_DAY_DEPENDENCE_PCT` | 0.70 |
| `SINGLE_REGIME_DEPENDENCE_PCT` | 0.70 |
