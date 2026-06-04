# Fill Model Calibration (v3.21.0 — ETAP 7)

## Purpose

Compare the deterministic shadow-fill assumptions used in
`shared/evidence_production.py` against real Alpaca paper fills,
**without ever touching the live broker** and **without mutating runtime
parameters**. The output is a JSON / Markdown report which the
operator and Multi-Agent Audit Board review.

This module is **review-gated** and **non-auto-apply by design**.

## Why

The 2026-06-02 audit board verdict reaffirmed
`APPROVE_PAPER_TRADING_WITH_WARNINGS` / `NOT_SAFE_FOR_LIVE_TRADING`.
Cross-cutting theme STRAT-003 explicitly named the shadow-vs-broker
gap as a risk: if the model under-estimates slippage by even 5 bps,
all downstream Wilson / bootstrap evidence bounds tilt towards an
inflated apparent edge.

## Inputs

A list of *paired* observations. Each pair carries:

| Field | Source |
|---|---|
| `shadow_fill_price`                  | `shared.evidence_production.estimate_shadow_fill` |
| `broker_paper_fill_price`            | Alpaca paper `/v2/orders/<id>` (operator-collected) |
| `reference_price`                    | mid at signal time |
| `expected_slippage_bps`              | shadow assumption (5 bps) |
| `actual_paper_slippage_bps`          | derived from broker fill vs reference |
| `spread_assumption_bps`              | shadow assumption (1 bps) |
| `observed_spread_bps`                | broker quote at fill |
| `fill_delay_seconds`                 | broker latency |
| `adverse_selection_after_fill_bps`   | price move 60 s after fill |
| `symbol` / `strategy`                | diagnostics |

If `shadow_fill_price` and `broker_paper_fill_price` are not BOTH
present the observation is dropped (`n_pairs_valid` reflects the
filtered count).

## Outputs

`build_calibration_report(pairs, window_days=90)` returns:

```text
{
  "produced_at": "...iso...",
  "mutates_runtime": False,                  # invariant
  "non_auto_apply": True,                    # invariant
  "evidence_source": "PAPER",                # never mixed with BACKTEST/REPLAY
  "min_paired_required": 20,
  "aggregate": {"n_paired": ..., "status": ..., "warning": ..., ...},
  "by_symbol":   {sym: <aggregate>, ...},
  "by_strategy": {strategy: <aggregate>, ...},
  "n_pairs_in":  <int>,
  "n_pairs_valid": <int>
}
```

## Status ladder

| Status | Condition |
|---|---|
| `INSUFFICIENT_BROKER_PAPER_DATA` | `n_paired < 20` |
| `WITHIN_TOLERANCE`               | `|slippage_delta_mean| <= 5 bps` |
| `MODEL_UNDERESTIMATES`           | `+5 < slippage_delta_mean < +15 bps` |
| `MODEL_DRIFT_HIGH`               | `slippage_delta_mean >= +15 bps` (WARN) |
| `MODEL_OVERESTIMATES`            | `slippage_delta_mean <= -5 bps` |

When `n_paired < 20` we explicitly skip the comparison; the operator
sees `INSUFFICIENT_BROKER_PAPER_DATA` rather than a false-confidence
calibration.

`MODEL_DRIFT_HIGH` surfaces a `REVIEW_FILL_MODEL` action in the
Operator Action Queue (see `docs/OPERATOR_ACTION_QUEUE.md`). The
runtime fill model is NOT auto-tuned — that is governed by Multi-Agent
Audit Board.

## CLI

```bash
python3 scripts/fill_model_calibration_report.py
python3 scripts/fill_model_calibration_report.py \
    --pairs-json /tmp/paired_fills.json
```

Writes:

- `docs/FILL_MODEL_CALIBRATION_LATEST.md`
- `learning-loop/FILL_MODEL_CALIBRATION_LATEST.json`

## Hard rules

- The runtime fill model parameters are **never mutated** by this
  module or CLI.
- No paid API is added.
- No LLM enters the runtime path.
- BACKTEST / REPLAY / COUNTERFACTUAL records are **never mixed** with
  PAPER observations — the report's `evidence_source` is always
  `PAPER`.
- The report bypasses the Evidence Budget if and only if it is
  marked `safety_report` (ETAP 9 invariant).
