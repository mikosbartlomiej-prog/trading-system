# Evidence Throughput Monitor

**Version:** v3.21.0 (2026-06-04)
**Module:** [`shared/evidence_throughput.py`](../shared/evidence_throughput.py)
**CLI:**    [`scripts/evidence_throughput_report.py`](../scripts/evidence_throughput_report.py)
**Tests:**  [`tests/test_evidence_throughput_v3210.py`](../tests/test_evidence_throughput_v3210.py)

## Purpose

The Strategy Quality Gate requires `n ≥ 50` closed paper trades before
it can promote a strategy to `ENABLED`. Without a deterministic measure
of *how fast* evidence is accumulating per strategy — across all four
evidence sources — operators cannot tell whether a strategy is on
track or stuck in a no-signal regime.

This module is the read-only aggregator that powers that visibility.

## Inputs (separate evidence sources — never mixed)

| Source         | On-disk path                                            | Notes                              |
|----------------|---------------------------------------------------------|------------------------------------|
| Opportunity    | `learning-loop/opportunity_ledger/<date>.jsonl`         | raw signals + gate decisions       |
| Shadow paper   | `learning-loop/shadow_ledger/<date>.jsonl`              | deterministic simulated fills      |
| Paper          | `learning-loop/paper_experiments/<date>.jsonl`          | broker paper executions only       |
| Counterfactual | `journal/autonomy/<date>.jsonl` (filtered by tag)       | `V320_COUNTERFACTUAL_COMPUTED` rows|

The counter for each source is reported **independently**. The
Strategy Quality Gate only counts `broker_paper_fills` toward `n=50`.

## Public API

### `compute_throughput(now=None, *, days_window=14, dirs=None)`

Returns a `ThroughputReport`. Pure function — no side effects.

### `StrategyThroughput.classify_status(...)`

Returns one of the seven statuses below.

## Statuses (closed enum)

| Status                          | Meaning                                                                                  |
|---------------------------------|------------------------------------------------------------------------------------------|
| `NO_EVIDENCE_FLOW`              | No raw signals and no fills over the window.                                             |
| `TOO_SLOW_TO_REACH_N50`         | Broker growth rate extrapolates to > 120 days to reach `n=50`, or zero growth.           |
| `HEALTHY_SHADOW_FLOW`           | Shadow simulated fills are growing at ≥ 1 / day.                                         |
| `HEALTHY_BROKER_PAPER_FLOW`     | Broker paper fills are growing at ≥ 0.5 / day.                                           |
| `NEEDS_MORE_SYMBOLS`            | Only one symbol observed in the window.                                                  |
| `NEEDS_MORE_SIGNAL_DENSITY`     | Low-but-present flow that does not meet any healthy threshold.                           |
| `NEEDS_MORE_REGIME_COVERAGE`    | Only one regime observed across the window.                                              |

## Contracts (do-not-cross)

* READ-ONLY: never places trades, never mutates state, never flips
  `EDGE_GATE_ENABLED`, never disables a strategy.
* Evidence sources stay SEPARATE. Shadow / counterfactual / broker
  counts are reported independently.
* Fail-soft: missing / malformed ledger files never raise; affected
  strategies report `NO_EVIDENCE_FLOW` and the run continues.
* Free operation: pure stdlib + repo helpers. No paid APIs.

## CLI

```bash
python3 scripts/evidence_throughput_report.py --days 14
python3 scripts/evidence_throughput_report.py --strategy momentum-long --json
```

## How operators read the output

1. Glance at the totals at the top of the report — confirm there is
   any evidence flow at all.
2. Look at the per-strategy rows for `HEALTHY_BROKER_PAPER_FLOW` —
   these are the only strategies that contribute to `n=50`.
3. For `TOO_SLOW_TO_REACH_N50` rows, check `estimated_days_to_n50`
   — that is the deterministic ETA, not a forecast.
4. For `NEEDS_MORE_*` rows, hand the report to the audit board with
   the related strategy proposal (universe expansion / regime relaxer)
   tagged. The Strategy Quality Gate, not this module, decides what
   to do.

## Behavior contract reminder

This module reports labels. Strategy Quality Gate decides actions.
The Multi-Agent Audit Board reviews promotions. **No automatic
mutations leave this module.**
