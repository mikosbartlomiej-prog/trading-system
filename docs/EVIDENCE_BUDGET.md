# Evidence Budget (v3.21.0 — ETAP 9)

## Purpose

Cap evidence-production work that runs on the free-tier runner so we
do not (a) burn the GH Actions minute budget or (b) starve safety
reports of CPU / disk / runtime. The budget is **deterministic**,
**offline**, **non-auto-apply**, and **free-tier safe**. It is
**governed by Multi-Agent Audit Board**.

## Invariant

```text
BUDGET_BYPASSES_SAFETY = True
```

Any action type in `SAFETY_ACTION_TYPES` is **always** allowed,
regardless of counters:

- `safety_report`
- `safe_mode_transition`
- `p0_audit_finding`
- `emergency_close_audit`
- `audit_emit`
- `kill_switch_alert`

Tests assert this invariant. The audit board verifies the constant is
`True` on every cycle.

## Limits

| Constant | Value |
|---|---:|
| `MAX_SHADOW_OBS_PER_DAY`         | 500 |
| `MAX_VARIANTS_EVALUATED_PER_DAY` | 20 |
| `MAX_SYMBOLS_PER_STRATEGY`       | 30 |
| `MAX_COUNTERFACTUALS_PER_RUN`    | 200 |
| `MAX_WORKFLOW_RUNTIME_SECONDS`   | 600 |
| `MAX_REPORT_SIZE_KB`             | 512 |

Per-day counters reset at UTC midnight. Per-run counters are reset by
calling `reset_run_counters()` at the top of a workflow. Per-strategy
counters key on the `EVIDENCE_BUDGET_STRATEGY` env var (caller supplies
the strategy name).

## API

```python
from evidence_budget import check_budget, reset_run_counters

allowed, reason = check_budget("shadow_observation", 1)
if not allowed:
    log(reason)            # surface; do NOT mutate strategy
    # The Operator Action Queue (ETAP 10) is the only
    # consumer that can escalate sustained limits.
```

Same input → same `(allowed, reason)` — deterministic. State is
persisted in `learning-loop/runtime_state.json::evidence_budget` via
`shared.runtime_state.write_section`.

## Storage

State section name: `evidence_budget`.
Writer: `evidence-budget` (must be added to runtime_state
INTRADAY_SECTIONS — done in v3.21.0).

Schema:

```json
{
  "date":                  "2026-06-04",
  "shadow_observation":    42,
  "variant_evaluation":    3,
  "symbol_for_strategy":   {"momentum": 5, "mean_reversion": 12},
  "counterfactual_run":    180,
  "workflow_runtime":      234,
  "report_size_kb":        21,
  "safety_bypasses":       4
}
```

## Hard rules

- Budget rejection NEVER mutates the strategy. It SURFACES the limit;
  the Operator Action Queue (ETAP 10) escalates sustained hits.
- Budget rejection NEVER suppresses safety reports.
- Budget rejection NEVER raises any risk threshold.
- No LLM calls. No paid APIs.
- Idempotent on retries: state is one JSON file under
  `learning-loop/runtime_state.json`.
