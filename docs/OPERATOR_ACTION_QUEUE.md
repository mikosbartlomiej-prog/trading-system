# Operator Action Queue (v3.21.0 — ETAP 10)

## Purpose

Centralise every item that needs operator review into a single
append-only ledger plus a deterministic markdown rollup. The queue is
the bridge between automated audit / calibration reports and human
decision making.

This module is **review-gated** and **non-auto-apply by design**. It is
**governed by Multi-Agent Audit Board**.

## Hard invariants

```text
QUEUE_NEVER_AUTO_APPLIES           = True
QUEUE_RISKY_ACTIONS_NON_AUTO_APPLY = True
```

Every action record carries `can_auto_apply = False`. The constructor
asserts the invariant. The audit board verifies the constants. The
status enum contains **no** `LIVE`, `LIVE_APPROVED`, or `LIVE_ENABLED`
values by construction.

## Action types

| Action type | Typical source |
|---|---|
| `REVIEW_STRATEGY`         | evidence_lower_bounds |
| `REVIEW_VARIANT`          | strategy_variant_quarantine |
| `DISABLE_CANDIDATE`       | evidence_lower_bounds (`EVIDENCE_REJECT`) |
| `KEEP_OBSERVING`          | experiment_scheduler |
| `ADD_DATA_SOURCE_REVIEW`  | learning-loop / curators |
| `CHECK_BROKER_PAPER`      | fill_model_calibration (`INSUFFICIENT_BROKER_PAPER_DATA`) |
| `REVIEW_GATE_CALIBRATION` | gate_calibration |
| `REVIEW_FILL_MODEL`       | fill_model_calibration (`MODEL_DRIFT_HIGH`) |
| `REVIEW_EDGE_GATE`        | strategy_quality_gate readiness |
| `NO_ACTION`               | book-keeping / informational |

## Record schema

```text
{
  "id":                              "oaq_<sha256 prefix>",
  "action_type":                     "REVIEW_FILL_MODEL",
  "severity":                        "P1",
  "source_module":                   "fill_model_calibration",
  "rationale":                       "MODEL_DRIFT_HIGH; review-gated; non-auto-apply by design",
  "evidence_links":                  ["docs/FILL_MODEL_CALIBRATION_LATEST.md"],
  "recommended_review_deadline_iso": "2026-06-11T00:00:00Z",
  "can_auto_apply":                  false,
  "status":                          "OPEN",
  "created_at":                      "2026-06-04T18:00:00Z",
  "affected_strategies":             [],
  "affected_symbols":                []
}
```

`id` is deterministic over `(action_type, source_module, severity,
rationale, sorted(evidence_links))`. Repeated `enqueue_action(...)`
calls with the same logical content are idempotent and produce only
one record on disk.

## Files

- `learning-loop/operator_action_queue.jsonl` — append-only ledger.
- `docs/operator_action_queue_LATEST.md`     — deterministic rollup.

Both paths are overridable via env vars `OPERATOR_ACTION_QUEUE_PATH`
and `OPERATOR_ACTION_QUEUE_REPORT_PATH` (used by tests).

## CLI

```bash
python3 scripts/operator_action_queue_render.py
python3 scripts/operator_action_queue_render.py --status OPEN
python3 scripts/operator_action_queue_render.py --severity P0
```

The CLI hard-asserts `QUEUE_NEVER_AUTO_APPLIES` and
`QUEUE_RISKY_ACTIONS_NON_AUTO_APPLY` before reading the queue, so any
tampering with the invariants surfaces as a hard error.

## Deterministic phrasing

Rationale text MUST use deterministic phrasing — the
`AAD_FORBIDDEN_WORDING_IN_NON_LIFECYCLE` audit flags phrases like
"manual approval required" or "operator decides". Use instead:

- "non-auto-apply by design"
- "governed by Multi-Agent Audit Board"
- "review-gated"
- "queued for evidence accumulation"
- "operator sweep recommended"

The module exposes these as `SAFE_PHRASES` for callers.

## Audit emission

Every `enqueue_action` writes a `Decision` to
`journal/autonomy/<date>.jsonl` (kind=trading) via
`shared.audit.write_audit_event`. The decision_type is mapped onto
the existing autonomy enum (`PAUSE_STRATEGY`). The audit emission is
fail-soft: a write error never breaks the queue.

## Hard rules

- Queue rejection / acceptance NEVER mutates the strategy registry,
  never raises risk, never flips `EDGE_GATE_ENABLED`.
- The queue does not call any paid API, does not call an LLM at
  runtime.
- The queue is review-gated; the only mutation is the operator
  manually moving an action to `ACKNOWLEDGED` / `DEFERRED` /
  `CLOSED_*` via `set_status`.
