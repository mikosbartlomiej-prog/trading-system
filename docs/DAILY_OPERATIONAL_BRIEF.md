========================================================================
# Daily Operational Brief — 2026-07-19
========================================================================

## TOP BANNER: YELLOW

**ALLOCATOR_BLOCKED — ALLOCATOR_BLOCKED_EQUITY_GAP**

Active blockers: equity_gap_stale_seconds=90435. No orders will be placed.

_The banner reflects the deterministic gate state only. LLM advisory output is informational and CANNOT override this verdict._

## Master verdict

- Decision: `ALLOCATOR_BLOCKED_EQUITY_GAP` [source: `learning-loop/system_activation_status_latest.json::master_decision`]
- Shadow simulator permitted: `True` [source: `system_activation_gate.shadow_only_allowed`]
- Reason: `equity_gap_stale_seconds=90435` [source: `system_activation_gate.reason`]

## Top blockers

- `equity_gap_stale_seconds=90435`

_Blockers are pulled from deterministic artefacts. LLM advisory output CANNOT add or remove items from this list._

## What changed since yesterday

- No prior brief sidecar found on disk. First brief or history not persisted — nothing to diff against.

## What operator must do

1. Review learning-loop/equity_gap_reconciliation_latest.json and the upstream account/equity sources; do NOT flip any broker or live-trading flag.

## Equity reconciliation

- verdict: `EQUITY_GAP_OK` [source: `learning-loop/equity_gap_reconciliation_latest.json::verdict`]
- gap_amount: `0.0` [source: `learning-loop/equity_gap_reconciliation_latest.json::gap_amount`]
- gap_pct: `0.0` [source: `learning-loop/equity_gap_reconciliation_latest.json::gap_pct`]
- block_allocator: `False` [source: `learning-loop/equity_gap_reconciliation_latest.json::block_allocator`]

## Broker repair queue

- Quarantined symbols: `0` [source: `learning-loop/broker_repair_required_latest.json::entries`]

## Safe-mode consistency

- verdict: `CONSISTENT` [source: `learning-loop/safe_mode_consistency_latest.json::verdict`]
- audit_enters: `0` [source: `learning-loop/safe_mode_consistency_latest.json::audit_enters`]
- audit_exits: `0` [source: `learning-loop/safe_mode_consistency_latest.json::audit_exits`]

## LLM advisory

- Provider mode: `UNAVAILABLE`
- **LLM advisory only — does not override deterministic gates.** Any recommendation surfaced below is informational. LLM has zero execution authority (`LLM_EXECUTION_AUTHORITY=false`).
- Mesh status: `CLAIM_UNSUPPORTED` [source: `learning-loop/llm_advisory_mesh_status_latest.json` missing]

## Unverified claims

- The earlier narrative claim of ``92 % readiness`` is `CLAIM_UNSUPPORTED` unless an artefact backs it up.
- The claim of ``18 LLM agents`` is `CLAIM_UNSUPPORTED` unless an artefact backs it up.
- The claim of ``80-day failure`` window is `CLAIM_UNSUPPORTED`. The deterministic LLM provider mode above is the only authoritative status.

## Standing markers
- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `NO_AUTO_BROKER_ACTION_FROM_THIS_REPORTER`
- `LLM_ADVISORY_ONLY`
- `TRADING_EXECUTION_ON=false`

---

_This brief is built by aggregating already-on-disk reporter artefacts. It never opens a network connection, never submits an order, never cancels an order, never closes a position, never mutates state.json or runtime_state.json, and never lets the LLM advisory output override the deterministic master gate._
