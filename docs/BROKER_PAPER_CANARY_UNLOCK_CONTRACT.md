# Broker-Paper Canary Unlock Contract (v3.29 — 2026-06-09)

This is the **only acceptable trading unlock path** in this
codebase. Every other path remains explicitly blocked.

## What "unlock trading" means in this system

- **It does NOT mean enabling live trading.** Live trading remains
  unsupported regardless of any unlock stage.
- **It does NOT mean bypassing evidence thresholds.** The v3.25
  thresholds (50 real opportunities / 20 outcomes) remain hard
  gates.
- **It does NOT mean allowing LLM agents to directly execute orders
  or mutate risk gates.** LLM authority is bounded by the v3.28
  authority model (max `L3_VETO_RECOMMEND_ONLY`, the risk-proposal
  agent at `L4_PROPOSE_CONFIG_CHANGE_ONLY`, `L5_EXECUTE_FORBIDDEN`
  sentinel).
- **It means**: progressing the broker-paper canary readiness from
  STAGE_0_SHADOW_ONLY toward STAGE_3_BROKER_PAPER_CANARY_ENABLED
  through a deterministic, evidence-gated path with explicit
  operator approval.

## Stages

| Stage | Meaning |
|---|---|
| `STAGE_0_SHADOW_ONLY` | Current default. Only shadow evidence is collected. No broker paper. No live. |
| `STAGE_1_BROKER_PAPER_CANARY_PROPOSAL` | Evaluator confirms evidence + LLM quality + alignment all pass. Proposal artifact written. No flag flipped. |
| `STAGE_2_BROKER_PAPER_CANARY_READY` | Operator has set `OPERATOR_APPROVED_BROKER_PAPER_CANARY=true`. Evaluator may now emit `BROKER_PAPER_CANARY_UNLOCK_READY`. No flag flipped. |
| `STAGE_3_BROKER_PAPER_CANARY_ENABLED` | A safe canary config flag has been flipped (in a separate, audited PR). Canary orders may execute under conservative limits. NOT broad paper trading. |
| `STAGE_4_BROADER_PAPER_TRADING_READY` | Future stage. Not in scope for v3.29. |
| `STAGE_5_LIVE_UNSUPPORTED` | **PERMANENTLY UNREACHABLE in this codebase.** Live trading is not supported. |

## Hard rule

**Live trading remains unsupported regardless of stage.**

## Hard gates (all must pass) for STAGE_2_BROKER_PAPER_CANARY_READY

The broker-paper canary unlock evaluator
([scripts/evaluate_broker_paper_canary_unlock.py](../scripts/evaluate_broker_paper_canary_unlock.py))
emits `BROKER_PAPER_CANARY_UNLOCK_READY` ONLY if every one of these
is true:

1. `real_market_opportunities_count >= 50`
2. `completed_shadow_outcomes_count >= 20`
3. No scaffold / halt-path record is counted as real-market evidence
4. `audit_bypass_findings_count == 0`
5. `exposure_cap_breach_count == 0`
6. `repeated_buy_violation_count == 0`
7. `unexplained_broker_state_conflicts_count == 0`
8. Crypto exposure policy reports stable
9. Trade reconstruction reports stable
10. `drawdown_guard_active == true`
11. `drawdown_guard_lowered == false`
12. `baseline_reset == false`
13. Notification flood guard active
14. Automated shadow pipeline status is `PROGRESSING` or
    `HEALTHY_BUT_NO_SIGNALS_YET`
15. `first_real_market_record_seen == true`
16. **LLM advisory quality is `LLM_ADVISORY_QUALITY_ACCEPTABLE`
    over at least 2 distinct successful runs.**
17. **LLM strategy alignment is
    `LLM_STRATEGY_ALIGNMENT_PASS` on the latest run.**
18. No secret leaks in any advisory output
19. No unsafe LLM suggestions
20. No provider failure state in the latest mesh run
21. **`OPERATOR_APPROVED_BROKER_PAPER_CANARY=true`** repo variable

## Operator approval

The repo variable `OPERATOR_APPROVED_BROKER_PAPER_CANARY` is the
explicit gate. Default `false`. Setting it does NOT unlock the
canary — it only allows the evaluator to advance to
`UNLOCK_READY`. A separate, audited PR is required to flip the
canary execution flag (see "What's NOT in scope" below).

```bash
# To approve (after evaluator reports the other 20 gates green):
gh variable set OPERATOR_APPROVED_BROKER_PAPER_CANARY --body "true"
```

## What the unlock orchestrator DOES

- Reads on-disk artefacts (evidence counters, workflow health,
  advisory quality, alignment status, position reconciliation).
- Computes a deterministic verdict.
- Writes
  `learning-loop/broker_paper_canary/unlock_readiness_latest.json`
  + `docs/BROKER_PAPER_CANARY_UNLOCK_STATUS.md`.
- **Never** flips a broker flag, never sets `ALLOW_BROKER_PAPER`,
  never sets `EDGE_GATE_ENABLED`, never sets
  `BROKER_EXECUTION_ENABLED`, never sets `LIVE_TRADING`, never
  mutates readiness counters, never imports the broker-orders
  module.

## What the unlock orchestrator does NOT do (canary scope and limits)

The canary is governed by [configs/broker_paper_canary.json](../configs/broker_paper_canary.json):

- `max_orders_per_day: 1`
- `max_notional_per_order_usd: 25`
- `allowed_asset_classes: ["us_equity"]`
- `crypto_enabled: false`
- `options_enabled: false`
- `max_daily_loss_usd: 25`
- `auto_disable_on_first_error: true`
- `auto_disable_on_drawdown_guard_touch: true`
- `auto_disable_on_llm_quality_regression: true`
- `auto_disable_on_reconciliation_mismatch: true`
- `require_safe_order_wrapper: true`
- `require_audit_record: true`
- `require_post_trade_reconciliation: true`

**No order is placed in v3.29 even when `UNLOCK_READY` is reached.**
The canary execution path requires a separate, audited PR that
introduces a safe canary executor and the corresponding feature
flag. v3.29 stops at `UNLOCK_READY` / `UNLOCK_READY_BUT_NO_SAFE_ENABLE_SWITCH`.

---

## v3.30 addendum (2026-06-09)

v3.30 ships the **canary pre-executor** in *preflight-only* mode and
flips `canary_execution_flag_present` to `true` in
[configs/broker_paper_canary.json](../configs/broker_paper_canary.json),
so the unlock evaluator can advance past
`UNLOCK_READY_BUT_NO_SAFE_ENABLE_SWITCH`. **But broker-paper trading
still does NOT happen** — every other safety contract is preserved.

### New terminal status

`BROKER_PAPER_CANARY_UNLOCK_READY_PRE_EXECUTOR_ONLY` — emitted when:

- All 21 v3.29 hard gates pass, AND
- `canary_execution_flag_present == true`, AND
- `canary_executor_mode == "preflight_only"`, AND
- `canary_order_placement_implemented == false`.

### New config fields

| Field | v3.30 value | Meaning |
| --- | --- | --- |
| `canary_execution_flag_present` | `true` | The architecture blocker is removed — a safe enable switch exists. |
| `canary_executor_mode` | `"preflight_only"` | The shipped executor never places orders; it only inspects gates. |
| `canary_order_placement_implemented` | `false` | The order-placement code path is deliberately NOT implemented in v3.30. |

### New CLI

[`scripts/run_broker_paper_canary.py`](../scripts/run_broker_paper_canary.py)
exposes the pre-executor on the command line. Default invocation is
`--preflight-only --dry-run`:

```bash
python3 scripts/run_broker_paper_canary.py
# verdict: CANARY_PREFLIGHT_DRY_RUN_OK — gates inspected, no order possible.
```

Even when every gate is green and the operator forces `--no-dry-run`,
the pre-executor's terminal verdict in v3.30 is:

```text
CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED
```

— and no order is placed. Flipping that to actual order placement
requires a follow-up audited PR that:

1. flips `canary_order_placement_implemented` to `true` in
   `configs/broker_paper_canary.json`,
2. introduces an order-placement code path constrained by the
   conservative limits in the same config,
3. requires post-trade reconciliation + audit record per order, and
4. uses `shared/alpaca_orders::safe_close` (or equivalent) for the
   close leg — no naked submit/place/close calls anywhere else.

### What v3.30 does NOT change

- LLM authority — still advisory only, max `L3_VETO_RECOMMEND_ONLY`.
- Live trading — still unsupported.
- Evidence thresholds — still 50 real opportunities + 20 outcomes.
- Observation records — diagnostic only; NEVER count toward the gate.
- Production LLM advisory schedule — still disabled by default.
- LLM pre-order veto — still disabled.

## What's NOT in scope for v3.29

- Flipping `ALLOW_BROKER_PAPER`, `EDGE_GATE_ENABLED`, or
  `BROKER_EXECUTION_ENABLED`.
- Building a canary executor.
- Building the canary safe-order wrapper.
- Building the canary post-trade reconciler.
- Building a canary kill-switch.
- Anything that places, modifies, or closes an order.

If the evaluator reports `BROKER_PAPER_CANARY_UNLOCK_READY` and no
safe enable switch exists in the codebase, it emits the special
status `BROKER_PAPER_CANARY_UNLOCK_READY_BUT_NO_SAFE_ENABLE_SWITCH`
and the operator opens a follow-up PR.

## Read-only by construction

[scripts/evaluate_broker_paper_canary_unlock.py](../scripts/evaluate_broker_paper_canary_unlock.py)
default mode is `--evaluate-only`. The script never imports
`shared/alpaca_orders.py`. The script never writes any field other
than the unlock artefacts.

`--apply-enable` exists in the CLI but is gated by every single
hard gate above + `OPERATOR_APPROVED_BROKER_PAPER_CANARY=true` +
branch-must-be-main + tests-must-pass + alignment must be PASS +
no live flags truthy + drawdown guard active. Even when all gates
pass, `--apply-enable` does NOT flip a broker flag — it can only
emit `BROKER_PAPER_CANARY_UNLOCK_READY_BUT_NO_SAFE_ENABLE_SWITCH`
because v3.29 does not include the safe enable switch.

## Standing markers always emitted

- `LLM_STRATEGY_ALIGNMENT_ENFORCED`
- `LLM_ADVISORY_ONLY_CONFIRMED`
- `DETERMINISTIC_GATES_REMAIN_FINAL`
- `LLM_OUTPUT_DOES_NOT_COUNT_AS_REAL_MARKET_EVIDENCE`
- `BROKER_PAPER_CANARY_ONLY_NOT_BROAD_TRADING`
- `LIVE_TRADING_UNSUPPORTED`

---

## v3.30.1 addendum (2026-06-09) — self-healing repair + auto-bounded calibration

Two non-flag-flipping additions:

1. **`scripts/repair_llm_quality_history.py`** — a read-only, append-
   only self-healing step that reconciles the latest
   `quality_review_latest.json` snapshot with `quality_history.jsonl`.
   It runs BEFORE `evaluate_unlock_readiness` (fail-soft wrapper) and
   guarantees that a stale, mock-pattern, placeholder, or self-
   inconsistent snapshot is recorded in history as
   `accepted_for_unlock_counting=false`. It never deletes or rewrites
   a history row. It refuses on truthy broker/live flags. Outputs:
     - `learning-loop/llm_advisory/quality_history_repair_latest.json`
     - `docs/LLM_QUALITY_HISTORY_REPAIR_STATUS.md`

2. **Self-gated bounded calibration workflow** — the legacy
   `LLM_QUALITY_CALIBRATION_ENABLED` repo variable is no longer
   required. `scripts/llm_quality_calibration_precheck.py` now
   evaluates 8 deterministic statuses (priority order):
     1. `CALIBRATION_SKIPPED_BROKER_FLAG_TRUTHY`
     2. `CALIBRATION_SKIPPED_PRODUCTION_SCHEDULE_ENABLED`
     3. `CALIBRATION_SKIPPED_DISABLED_BY_OPERATOR`
        (optional opt-out: `LLM_QUALITY_CALIBRATION_DISABLED=true`)
     4. `CALIBRATION_SKIPPED_NON_FREE_PROVIDER`
     5. `CALIBRATION_SKIPPED_NO_GEMINI_KEY`
     6. `CALIBRATION_SKIPPED_ALREADY_CALIBRATED`
     7. `CALIBRATION_SKIPPED_BUDGET_EXHAUSTED`
     8. `CALIBRATION_PROCEEDING`

The calibration workflow only invokes Gemini when status is
`CALIBRATION_PROCEEDING`. All other status branches early-exit
without consuming any provider budget.

## Standing markers added in v3.30.1

- `NO_MANUAL_REPO_VARIABLE_REQUIRED_FOR_CALIBRATION`
- `STALE_MOCK_QUALITY_NEVER_COUNTS_AS_ACCEPTABLE`
- `CALIBRATION_BOUNDED_FREE_ONLY_GEMINI`
- `PRODUCTION_LLM_SCHEDULE_REMAINS_DISABLED`
- `LLM_PRE_ORDER_VETO_REMAINS_DISABLED`
- `CANARY_PRE_EXECUTOR_PREFLIGHT_ONLY`
- `NO_ORDER_PLACEMENT`
- `BROKER_PAPER_CANARY_ONLY_NOT_BROAD_TRADING`
- `LIVE_TRADING_UNSUPPORTED`
- `DETERMINISTIC_GATES_REMAIN_FINAL`

LLM remains advisory only. Canary pre-executor remains preflight-only.
No order placement is implemented in v3.30.1. Live trading remains
unsupported.
