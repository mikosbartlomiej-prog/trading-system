# Signal Density Audit

**Version:** v3.21.0 (2026-06-04)
**Module:** [`shared/signal_density_audit.py`](../shared/signal_density_audit.py)
**CLI:**    [`scripts/signal_density_report.py`](../scripts/signal_density_report.py)
**Tests:**  [`tests/test_signal_density_audit_v3210.py`](../tests/test_signal_density_audit_v3210.py)

## Purpose

A strategy marked `enabled = true` that generates zero / sparse /
overly-noisy signals is a hidden liability. It blocks paper evidence
accumulation, gives the LLM Senior PM a fake roster entry, and
silently shifts allocation budget away from honest performers.

This module is the read-only classifier that scans the same evidence
sources as [`evidence_throughput`](EVIDENCE_THROUGHPUT.md) and labels
each strategy with a density-quality status. The labels feed the
audit board reviewing strategy promotions and the operator-facing
decision pack — they are never auto-applied.

## Inputs

The module re-uses [`shared/evidence_throughput.py`](../shared/evidence_throughput.py)
to read:

* `learning-loop/opportunity_ledger/<date>.jsonl`
* `learning-loop/shadow_ledger/<date>.jsonl`
* `learning-loop/paper_experiments/<date>.jsonl`
* `journal/autonomy/<date>.jsonl` (counterfactual lines only)

## Public API

### `run_density_audit(now=None, *, days_window=14, dirs=None, emit_audit=True)`

Returns a `DensityAuditReport`. By default each per-strategy status
assignment is appended to `journal/autonomy/<date>.jsonl` with the
canonical tag `V321_SIGNAL_DENSITY_AUDIT`.

### `classify_density_status(record)`

Pure function that maps one `DensityRecord` to a status. Useful for
unit testing rule changes without re-reading the ledgers.

## Statuses (closed enum, order = rule priority)

| Status                            | Meaning                                                                                  |
|-----------------------------------|------------------------------------------------------------------------------------------|
| `DEAD_STRATEGY`                   | 0 raw signals AND 0 fills over the window.                                               |
| `TOO_SPARSE`                      | < 5 raw signals AND 0 shadow / broker fills.                                             |
| `HIGH_REJECTION_BUT_PROMISING`    | ≥ 70% rejected AND the accepted minority averages confidence ≥ 0.65.                     |
| `NOISY_STRATEGY`                  | ≥ 20 signals AND avg confidence ≤ 0.45 AND ≥ 60% scored under 0.50.                      |
| `NEEDS_VARIANT_DISCOVERY`         | One-symbol OR one-regime dependence with < 15 raw signals.                               |
| `NEEDS_UNIVERSE_EXPANSION`        | Healthy density (≥ 15 signals, avg conf ≥ 0.50) but pinned to a single symbol.           |
| `HEALTHY_DENSITY`                 | None of the above triggered.                                                             |

## Contracts (do-not-cross)

* READ-ONLY. The module never places trades, never mutates state,
  never auto-disables a strategy, never flips `EDGE_GATE_ENABLED`.
* Evidence sources are aggregated via `evidence_throughput` —
  SHADOW / COUNTERFACTUAL / BROKER_PAPER counters remain separate.
* Audit emit per status: `V321_SIGNAL_DENSITY_AUDIT`.
* Fail-soft. Missing / malformed records never raise.

## CLI

```bash
python3 scripts/signal_density_report.py --days 14
python3 scripts/signal_density_report.py --strategy momentum-long --json
python3 scripts/signal_density_report.py --no-audit   # dry-run
```

## How operators read the output

1. Sort by status in the human-readable output — the `DEAD_STRATEGY`
   list highlights ghost strategies that should be hand-archived (the
   archival decision itself is governed by the Strategy Quality Gate;
   this module does not perform the disable).
2. `TOO_SPARSE` rows are candidates for either universe expansion or
   strategy variant discovery — pair them with the audit board.
3. `NOISY_STRATEGY` rows almost always indicate a missing filter; the
   audit board owns that conversation.
4. `HIGH_REJECTION_BUT_PROMISING` rows are the high-value findings —
   the gate is correctly screening noise and there is genuine edge in
   the accepted minority. Operator may request a variant proposal via
   the Strategy Quality Gate quarantine pipeline.
5. `HEALTHY_DENSITY` rows should match the strategies that the
   Strategy Quality Gate is already scoring.

## Behavior contract reminder

The audit board reviews labels. The Strategy Quality Gate decides
promotions / quarantine. This module reports. Non-auto-apply by
design.
