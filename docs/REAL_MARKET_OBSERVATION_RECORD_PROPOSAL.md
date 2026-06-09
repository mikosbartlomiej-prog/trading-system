# Real-Market Observation Record Proposal (v3.29.1 — deferred to v3.30)

## Status

**Decision (v3.29.1): DEFERRED.** No schema change in this sprint.
This document is the operator-facing proposal for the v3.30 work.

## Motivation

The v3.27.x shadow pipeline only records `REAL_MARKET_DATA` when a
strategy actually fires a signal. The v3.27.2 progress monitor's
`AUTOMATED_EVIDENCE_STUCK_GENERATOR_TOO_RESTRICTIVE` status surfaces
the case where bars are fresh and sufficient but the generator
emits no record. The operator currently has no append-only artefact
that captures *what the system saw and chose to skip*.

Adding a sibling record type would close this gap without changing
canary unlock semantics.

## Proposed schema (NOT YET APPLIED)

A new `evidence_quality` enum value plus a sibling `record_type` field:

```json
{
  "evidence_quality": "REAL_MARKET_DATA_OBSERVATION",
  "record_type":      "NO_TRADE_OBSERVATION",
  "broker_order_submitted":   false,
  "broker_execution_enabled": false,
  "affects_readiness_gate":   false,
  ...
}
```

## Hard rules (carry forward into v3.30 implementation)

- Observation records do **NOT** increment `real_market_opportunities_count`.
- Observation records do **NOT** count toward the 50-opportunities
  unlock threshold.
- Observation records **MUST NOT** unlock broker paper.
- Observation records exist to **diagnose** no-signal regimes and
  feed LLM advisory + strategy-tuning proposals.
- All existing pinned safety enums apply unchanged
  (`affects_readiness_gate=[false]`, `broker_order_submitted=[false]`,
  `broker_execution_enabled=[false]`).

## Why deferred

1. The current shadow-evidence schema is consumed by 6+ tests + 4
   monitor scripts + the v3.27.x progress monitor + the v3.25
   readiness gate. Introducing a new `evidence_quality` value
   requires coordinated updates to all of them.
2. The v3.27.2 progress monitor already surfaces the
   `STUCK_GENERATOR_TOO_RESTRICTIVE` mode that observation records
   would diagnose — the operator already has visibility.
3. v3.29.1's scope (LLM quality truth source + evidence acceleration
   analyzer) achieves the same diagnostic goal without schema
   change.

## What v3.29.1 SHIPS INSTEAD

- `shared/real_market_evidence_accelerator.py` — analyses the
  workflow_health_history and emits the dominant diagnostic token
  + safe recommended actions.
- `scripts/evaluate_real_market_evidence_acceleration.py` — CLI
  wrapper.
- `.github/workflows/real-market-evidence-accelerator.yml` —
  daily read-only workflow that writes
  `learning-loop/shadow_evidence/acceleration_latest.json` +
  `docs/REAL_MARKET_EVIDENCE_ACCELERATION.md`.

## Follow-up action items (v3.30 spec sketch)

1. Add `REAL_MARKET_DATA_OBSERVATION` to the
   `EVIDENCE_QUALITY_*` enum in
   `shared/shadow_evidence_counters.py`.
2. Add `NO_TRADE_OBSERVATION` to the record schema (optional
   `record_type` field; defaults to absent on legacy records).
3. Wire the observation emitter into
   `scripts/run_signal_shadow_evidence_collection.py` AFTER the
   normal record-emission loop — emit one observation per
   considered symbol when no signal fired and bars were
   sufficient.
4. Pin the new safety contract in the JSON Schema:
   `affects_readiness_gate=[false]` + the existing 6 pins remain
   unchanged. Add `record_type` enum:
   `["NORMAL", "NO_TRADE_OBSERVATION"]`.
5. Update the v3.27.x progress monitor + v3.29.x acceleration
   analyzer to consume the new diagnostic data.
6. Add a 12-test suite that verifies observation records NEVER
   advance the canary, NEVER increment opportunities, and NEVER
   carry `affects_readiness_gate=true`.

## Safety markers (apply to this proposal AND its future implementation)

- `LLM_OUTPUT_DOES_NOT_COUNT_AS_REAL_MARKET_EVIDENCE`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `BROKER_PAPER_CANARY_ONLY_NOT_BROAD_TRADING`
- `LIVE_TRADING_UNSUPPORTED`
- `DETERMINISTIC_GATES_REMAIN_FINAL`
