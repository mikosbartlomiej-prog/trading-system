# Signal/Shadow Evidence Collection Runbook (v3.26)

**Scope:** signal/shadow **only**. Broker paper is **blocked**. Live trading is **unsupported**.

This runbook describes how to run, observe, and audit the v3.26
evidence-collection pipeline that feeds the
`trading_unlock_readiness` gate toward an eventual broker-paper
canary readiness. **No** step in this runbook submits orders,
closes positions, modifies positions, or hits a live broker
endpoint.

## What this runbook is

A scaffolding plus operator playbook for the **signal/shadow**
phase that comes after v3.25's crypto position-sizing root-cause
fix. The collector observes (or in scaffold mode, mocks) candidate
trade decisions, records them as evidence in append-only JSONL,
and increments deterministic counters that
`shared/trading_unlock_readiness.py` reads.

## What this runbook is **not**

- It is **not** broker paper execution.
- It is **not** live trading.
- It is **not** authority to flip `EDGE_GATE_ENABLED`.
- It is **not** authority to flip `ALLOW_BROKER_PAPER`.
- It is **not** authority to lower the drawdown guard, reset the
  baseline, restore quarantined scripts, or clear the LLM override
  lock.

## Hard safety rules

The collector script and its dependencies enforce these at
multiple layers:

- **All order submission paths must remain disabled.**
- The collector script (`scripts/run_signal_shadow_evidence_collection.py`)
  refuses to proceed if `ALLOW_BROKER_PAPER`, `EDGE_GATE_ENABLED`,
  `BROKER_EXECUTION_ENABLED`, `LIVE_TRADING`, `LIVE_ENABLED`,
  `GO_LIVE`, or `LIVE_TRADING_ENABLED` is truthy.
- The collector does **not** import any function from
  `shared/alpaca_orders.py` (asserted by
  `tests/test_signal_shadow_collection_no_broker_execution_v3260.py`).
- Every emitted shadow record carries
  `broker_execution_enabled=false` and
  `broker_order_submitted=false` per the schema at
  `learning-loop/shadow_evidence/schema.json`.

## Pre-flight (always run first)

```python
from shared.signal_shadow_preflight import (
    PreflightInputs, run_preflight,
)
report = run_preflight(PreflightInputs(
    open_orders_count=0,
    open_equity_positions_count=0,
    crypto_positions_reconciled=True,
))
assert report.verdict == "SIGNAL_SHADOW_PREFLIGHT_PASS"
```

Expected confirmations in v3.26:

- `BROKER_EXECUTION_DISABLED_CONFIRMED`
- `BROKER_PAPER_DISABLED_CONFIRMED`
- `LIVE_TRADING_UNSUPPORTED_CONFIRMED`
- `EDGE_GATE_DISABLED_CONFIRMED`
- `CRYPTO_GUARDS_PRESENT_CONFIRMED`
- `AUDIT_BYPASS_INVARIANT_CONFIRMED`
- `QUARANTINED_SCRIPTS_STILL_DISABLED_CONFIRMED`
- `UNLOCK_READINESS_VERDICT_CONFIRMED`
- `BROKER_PAPER_NOT_READY_CONFIRMED`
- `BASELINE_UNCHANGED_CONFIRMED`
- `DRAWDOWN_GUARD_NOT_LOWERED_CONFIRMED`
- `OPEN_ORDERS_ZERO_CONFIRMED` (when supplied)
- `OPEN_EQUITY_POSITIONS_ZERO_CONFIRMED` (when supplied)
- `CRYPTO_POSITIONS_RECONCILED_CONFIRMED` (when supplied)

Any blocker downgrades the verdict to
`SIGNAL_SHADOW_PREFLIGHT_BLOCKED` and the collector script refuses
to proceed.

## Collector script

```sh
python3 scripts/run_signal_shadow_evidence_collection.py --max-records 10
```

Without market data the collector returns
`SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA` (counters incremented
under `halt_path_opportunities_count`). With `--allow-without-market-data`
it emits scaffold-only records used during smoke tests; this is the
v3.26 starting state.

The collector returns one of:

- `SHADOW_COLLECTION_PROCEEDING` — preflight passed, records were
  emitted (scaffold or real).
- `SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA` — preflight passed
  but the collector chose to skip emitting records due to missing
  market data.
- `SHADOW_COLLECTION_REFUSED_PREFLIGHT_FAILED` — preflight had
  blockers.
- `SHADOW_COLLECTION_REFUSED_BROKER_EXECUTION_ENABLED` — any
  broker-execution env flag was set.

## Evidence layout

```text
learning-loop/shadow_evidence/
├── schema.json                       # shadow decision JSON schema
├── evidence_counters_latest.json     # monotonic counters
└── records_YYYY-MM-DD.jsonl          # append-only daily records
```

The schema pins `broker_order_submitted: {enum: [false]}` and
`broker_execution_enabled: {enum: [false]}` so any future caller
attempting to emit a true-flag record will fail JSON validation
loudly.

## Counters and unlock thresholds

The v3.25 `trading_unlock_readiness` module consumes:

- `normal_non_halt_opportunities_count >= 50`
- `completed_shadow_outcomes_count >= 20`
- `audit_bypass_findings_count == 0`
- `exposure_cap_breach_count == 0`
- `repeated_buy_violation_count == 0`
- daily learning stable, trade reconstruction stable, explicit
  operator approval

Until ALL of these are true, the verdict stays
`SIGNAL_SHADOW_UNLOCK_READY` and broker paper canary stays
**`BROKER_PAPER_CANARY_NOT_READY`**.

## Failure modes and recovery

| Symptom | Recovery |
|---|---|
| Preflight fails with `audit-bypass invariant` blocker | Inspect `learning-loop/position_reconciliation/audit_bypass_investigation_latest.json`. If a new `LEGACY_DANGEROUS` file appears, quarantine it via `git mv` to `scripts/quarantined_legacy_order_scripts/<name>.py.disabled` per v3.23.3 procedure. **Do not** add the file to the allow-list. |
| Preflight fails with `quarantine integrity` blocker | A `.py.disabled` was renamed back to `.py`, removed, or moved. Restore from git history. Do NOT delete evidence. |
| Preflight fails with `unlock verdict` blocker | Check `shared/trading_unlock_readiness.py::evaluate_from_current_repo_state()`. If `EDGE_GATE_ENABLED` or `ALLOW_BROKER_PAPER` are truthy, unset them. **Do not raise them deliberately to pass.** |
| Collector returns `SKIPPED_NO_MARKET_DATA` repeatedly | Expected in v3.26. Real market-data wiring is deferred. |
| Counters file refuses to persist | The `save_counters()` call checks the in-memory `safety_invariants`. If any of `broker_order_submitted_ever`, `live_trading_enabled`, `broker_paper_enabled` is True, the persistence path raises. Inspect the caller. |

## Operator commands that are explicitly forbidden in v3.26

- `export ALLOW_BROKER_PAPER=true`
- `export EDGE_GATE_ENABLED=true`
- `export LIVE_TRADING=true`
- Editing `state.json::cumulative.starting_equity`
- Editing `config/aggressive_profile.json::risk_caps.daily_drawdown_pct` to anything weaker than -3.0%
- Re-introducing any `scripts/emergency_close_*.py` from the
  quarantine
- Adding `scripts/quarantined_legacy_order_scripts/` to
  `shared/audit_bypass_detector.py::ALLOW_LIST`
