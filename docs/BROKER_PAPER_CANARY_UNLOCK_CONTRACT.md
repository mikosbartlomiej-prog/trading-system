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
