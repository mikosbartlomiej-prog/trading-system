# Experiment Scheduler — v3.20 ETAP 7

**Module:** `shared/experiment_scheduler.py`
**CLI:** `scripts/experiment_scheduler_run.py`
**Tests:** `tests/test_experiment_scheduler_v3200.py`
**Outputs:**
- `learning-loop/experiment_plans/experiment_plan_<date>.json`
- `docs/experiment_plan_LATEST.md`

---

## Why this exists

The system runs paper-only and accumulates partial evidence per
strategy / symbol / regime / confidence bucket. The audit-board verdict
on 2026-06-02 reaffirmed `NOT_SAFE_FOR_LIVE_TRADING` and asked for a
deterministic plan that guides operator observation effort WITHOUT
touching the runtime trading path.

`shared/experiment_scheduler.py` reads:

- Strategy ranking from `shared/strategy_ranking.py` (best-effort)
- The opportunity ledger (best-effort)
- Confidence calibration buckets (best-effort)
- Evidence lower bounds per regime (best-effort)
- Quarantined variants from `shared/strategy_variant_quarantine.py`

…and emits an OBSERVATION-ONLY plan.

## What the plan looks like

```jsonc
{
  "ts_iso":                       "2026-06-04T...",
  "plan_date":                    "2026-06-04",
  "strategies_to_observe":        [...],
  "symbols_to_observe":           [...],
  "variants_to_replay":           [...],
  "rejected_signals_to_analyze":  [...],
  "confidence_buckets_needing_data": [...],
  "underrepresented_regimes":     [...],
  "invariants": {
    "SCHEDULER_NEVER_PLACES_TRADES": true,
    "SCHEDULER_NEVER_RAISES_RISK":   true,
    "SCHEDULER_NEVER_CHANGES_GATES": true
  }
}
```

## Invariants enforced in code

```python
SCHEDULER_NEVER_PLACES_TRADES = True
SCHEDULER_NEVER_RAISES_RISK   = True
SCHEDULER_NEVER_CHANGES_GATES = True
```

The tests assert that:

- An underrepresented regime gets priority (lowest sample count first).
- A weak strategy does NOT get larger risk (plan rows carry no
  size / leverage / kelly / weight knobs).
- `generate_plan` does NOT mutate `learning-loop/state.json` or
  `learning-loop/runtime_state.json`.
- Output is deterministic for fixed input (modulo timestamp).
- The plan can be written to disk in both JSON and Markdown.

## Sources of inputs

| Section | Source |
| ------- | ------ |
| `strategies_to_observe` | `shared/strategy_ranking.py::rank_strategies` |
| `symbols_to_observe` | Opportunity ledger (paper experiment) |
| `variants_to_replay` | `shared/strategy_variant_quarantine.load_quarantined_variants` |
| `rejected_signals_to_analyze` | Opportunity ledger entries with `rejection_reason` |
| `confidence_buckets_needing_data` | `shared/confidence_calibration.py` output (best-effort) |
| `underrepresented_regimes` | Evidence lower bounds (best-effort) |

All sources are optional. Missing inputs simply produce empty
sections.

## CLI

```
python3 scripts/experiment_scheduler_run.py
python3 scripts/experiment_scheduler_run.py \
    --ranking learning-loop/strategy_ranking_latest.json \
    --ledger learning-loop/opportunity_ledger.json
```

`--no-write` prints the plan to stdout without persisting it.
`--audit` emits a fail-soft JSONL audit event.

## What this module does NOT do

- It does NOT place real trades.
- It does NOT raise position sizes, leverage, or risk limits.
- It does NOT change gate flags or kill switches.
- It does NOT bypass the audit log.
- It does NOT mix BACKTEST/REPLAY/COUNTERFACTUAL evidence with PAPER.
- It does NOT add paid APIs / databases / hosting / monitoring.
- It does NOT add LLM/agents to the runtime trading path.
- It does NOT flip `EDGE_GATE_ENABLED`.
- It does NOT introduce LIVE_APPROVED status.
- It does NOT add network calls.
