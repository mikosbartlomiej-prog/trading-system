# Trading Unlock Readiness (v3.25)

**Status as of v3.25.0:** the maximum permissible unlock verdict is
`SIGNAL_SHADOW_UNLOCK_READY`. Broker paper remains **BLOCKED**.
Live trading is permanently `LIVE_TRADING_NOT_SUPPORTED`.

## Verdict ladder (`shared/trading_unlock_readiness.py`)

| Verdict | Meaning |
|---|---|
| `TRADING_UNLOCK_BLOCKED` | One or more hard safety conditions fail. No unlock at any tier. |
| `SIGNAL_SHADOW_UNLOCK_READY` | Hard safety conditions pass. Operator may run signal/shadow flows that **observe and log** would-be trades but never reach the broker. |
| `BROKER_PAPER_CANARY_NOT_READY` | Informational — what is missing for paper canary to be ready. |
| `BROKER_PAPER_CANARY_READY` | Paper canary may be enabled. **Never** returned in v3.25 because evidence files do not exist yet. |
| `LIVE_TRADING_NOT_SUPPORTED` | Never returned as a positive verdict. Marker constant only. |

## Hard safety conditions for `SIGNAL_SHADOW_UNLOCK_READY`

All must hold simultaneously. If any fails, the verdict drops to
`TRADING_UNLOCK_BLOCKED`.

- `audit_bypass_invariant_satisfied` — `shared/audit_bypass_detector.py` returns `invariant_satisfied=True`
- `no_active_legacy_dangerous_order_script` — `NO_ACTIVE_LEGACY_DANGEROUS_ORDER_SCRIPT=True`
- `open_equity_positions_count == 0`
- `open_orders_count == 0`
- `crypto_positions_reconciled == True` (matches the v3.23.3.3 dashboard verification)
- `crypto_hard_exposure_caps_implemented == True` (shipped in v3.25 via `shared/crypto_exposure_policy.py`)
- `drawdown_attribution_near_complete == True` (achieved in v3.24 reattribution)
- `baseline_silently_reset == False`
- `drawdown_guard_active_or_acknowledged == True`
- `edge_gate_enabled == False`
- `allow_broker_paper == False`
- `unresolved_runaway_loop_finding == False`
- `v3_25_tests_pass == True`

## Additional evidence required for `BROKER_PAPER_CANARY_READY`

All of these on top of signal/shadow conditions. None can exist yet.

- `normal_non_halt_opportunities_count >= 50`
- `completed_shadow_outcomes_count >= 20`
- `audit_bypass_findings_count == 0`
- `unexplained_exposure_growth_count == 0`
- `repeated_buy_loop_violations_count == 0`
- `crypto_exposure_cap_breached_count == 0`
- `daily_learning_stable == True`
- `trade_reconstruction_stable == True`
- `explicit_operator_approval_for_broker_paper == True`

## Live trading

`LIVE_TRADING_NOT_SUPPORTED` is permanent. No combination of inputs
produces a positive live verdict. The module enforces this via
`LIVE_TRADING_NEVER_RETURNS_READY = True`.

## What the readiness module does NOT do

- Does NOT submit orders.
- Does NOT enable broker_paper or live trading.
- Does NOT lower the drawdown guard.
- Does NOT reset the equity baseline.
- Does NOT flip `EDGE_GATE_ENABLED`.
- Does NOT mutate any state file.

## Operator usage

```python
from shared.trading_unlock_readiness import (
    UnlockReadinessInputs, evaluate_unlock_readiness,
)

report = evaluate_unlock_readiness(UnlockReadinessInputs(
    audit_bypass_invariant_satisfied=True,
    crypto_hard_exposure_caps_implemented=True,
    # ... other current-state booleans ...
))
print(report.verdict, report.missing_for_broker_paper)
```

Convenience helper that uses current env flags + minimal repo state:

```python
from shared.trading_unlock_readiness import (
    evaluate_from_current_repo_state,
)
report = evaluate_from_current_repo_state()
# Expected verdict in v3.25: SIGNAL_SHADOW_UNLOCK_READY
```

---

## v3.26 update — signal/shadow evidence collection scaffolding

v3.26 ships the operator scaffolding for the
`SIGNAL_SHADOW_UNLOCK_READY` tier:

- `shared/signal_shadow_preflight.py` — single-call preflight
  validator. Returns `SIGNAL_SHADOW_PREFLIGHT_PASS` or
  `SIGNAL_SHADOW_PREFLIGHT_BLOCKED` plus 14 named confirmation
  tokens (when satisfied).
- `shared/shadow_evidence_counters.py` — monotonic counter
  module persisting under
  `learning-loop/shadow_evidence/evidence_counters_latest.json`.
- `learning-loop/shadow_evidence/schema.json` — JSON Schema for
  shadow decision records. `broker_order_submitted` and
  `broker_execution_enabled` are pinned to `enum: [false]`.
- `scripts/run_signal_shadow_evidence_collection.py` — dry-run
  collector. Refuses to proceed if any broker-execution env flag
  is truthy.
- `docs/SIGNAL_SHADOW_EVIDENCE_COLLECTION_RUNBOOK.md` — operator
  runbook.
- `docs/SHADOW_EVIDENCE_PROGRESS.md` — progress report.

After v3.26 ships, the verdict ladder is unchanged. The maximum
permissible verdict remains `SIGNAL_SHADOW_UNLOCK_READY`. Broker
paper remains `BROKER_PAPER_CANARY_NOT_READY` until ALL of the
v3.25 evidence thresholds are met AND the operator gives explicit
approval.
