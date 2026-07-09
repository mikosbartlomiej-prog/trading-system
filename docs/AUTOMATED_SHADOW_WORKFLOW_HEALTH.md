# Automated Shadow Workflow Health (v3.27.1)

**Generated:** `2026-07-09T16:13:39.743545+00:00`
**Source:** `learning-loop/shadow_evidence/workflow_health_latest.json`
**Verdict:** **`AUTOMATED_PIPELINE_HEALTHY_NO_REAL_DATA_YET`**
**Standing markers:** `BROKER_PAPER_CANARY_STILL_BLOCKED`, `LIVE_TRADING_UNSUPPORTED`

## Rationale

- real_market_opportunities_count=0; workflow + data path appear healthy

## Workflow run

| Field | Value |
|---|---|
| Last run id | `29032544059` |
| Last run conclusion | `success` |
| Last collector status | `SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA` |
| Last resolver status | `RESOLVED` |

## Canary-gate counters

| Metric | Value |
|---|---:|
| `real_market_opportunities_count` (target 50) | **0** |
| `completed_shadow_outcomes_count` (target 20) | **0** |
| `audit_bypass_findings_count` | 0 |
| `exposure_cap_breach_count` | 0 |
| `repeated_buy_violation_count` | 0 |
| `unexplained_broker_state_conflicts_count` | 0 |

## Per-symbol diagnostic tokens (most recent cycle)

| Token | Symbols |
|---|---:|
| (none) | 0 |

## Safety invariants (from counters file)

- `broker_order_submitted_ever`: `false`
- `live_trading_enabled`: `false`
- `broker_paper_enabled`: `false`
- `edge_gate_enabled`: `false`
- `baseline_reset`: `false`
- `drawdown_guard_lowered`: `false`

## What this report does NOT do

- Does NOT submit orders.
- Does NOT enable broker paper.
- Does NOT enable live trading.
- Does NOT log or commit secret values.
- Does NOT modify positions.
- Does NOT lower the drawdown guard.
- Does NOT reset the equity baseline.
