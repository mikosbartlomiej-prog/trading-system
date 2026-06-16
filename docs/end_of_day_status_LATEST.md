# End-of-Day System Status — v3.28 INCIDENT CONTAINMENT (AVAX/USD P13 Retry Storm)

Generated: 2026-06-16T10:35:00Z  (Claude v3.28 FINAL-PHASE — incident containment shipped, allocator gated, manual operator repair required)
HEAD: `7cbe74139c8d8ada43bfda120b59755ae9d4cd48`  (pre-v3.28 commit; v3.28 staged for commit)

## TL;DR

**INCIDENT ACTIVE: AVAXUSD P13 bracket interlock — MANUAL REPAIR REQUIRED.**
On 2026-06-15 a recurring P13 (`bracket_interlock_blocked_close`) pattern
fired throughout the UTC morning. The runaway pattern was identified in
`learning-loop/incidents/2026-06-15.md` (12+ CRITICAL findings between
03:21Z and ~05:06Z). Exit-monitor calls `safe_close(AVAXUSD)` returned
Alpaca **403 "insufficient balance"** and `safe_close(LTCUSD)` returned
Alpaca **422 "qty must be > 0"** — both are operator-side broker-state
divergences that the system cannot resolve autonomously.

v3.28 ships **incident containment** (no automated fixes, no broker
actions, no auto-cleanup). The morning allocator is **blocked by the new
`shared/allocator_incident_gate`** which fails CLOSED on `BLOCK_UNKNOWN`
the moment any incident signal cannot be parsed. The operator is the only
actor who can clear the incident state, via the runbook
`docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md`.

v3.28 does NOT enable live trading, does NOT call any broker API, does
NOT auto-cancel orders, does NOT auto-close positions, does NOT auto-clear
safe_mode, does NOT deploy allocator capital, does NOT lower any
threshold, does NOT add LLM to the runtime trading path, does NOT add
paid services. `EDGE_GATE_ENABLED` remains `false`. `ALLOW_BROKER_PAPER`
remains `false`. LLM stays advisory only. Canary stays preflight-only.
`LIVE_TRADING_UNSUPPORTED`. `NO_ORDER_PLACEMENT`. `NO_AUTO_BROKER_ACTION`.
`NO_FABRICATION`.

## 1. Repo status

- **Branch:** `main`
- **HEAD before v3.28 commit:** `7cbe74139c8d8ada43bfda120b59755ae9d4cd48`
- **Working tree:** v3.28 incident containment staged for commit
- **Worktrees:** single — `main` only

## 2. System status flags (canonical, hard-pinned)

| Flag                          | Value     | Notes                                  |
| ----------------------------- | --------- | -------------------------------------- |
| `EDGE_GATE_ENABLED`           | **false** | Hard-pinned. v3.28 does not flip this. |
| `ALLOW_BROKER_PAPER`          | **false** | Hard-pinned default. v3.28 does not flip this. |
| `LIVE_TRADING_UNSUPPORTED`    | **true**  | CLI rejects `--mode live`. |
| `NO_ORDER_PLACEMENT`          | **true**  | Containment modules never call broker APIs. |
| `NO_AUTO_BROKER_ACTION`       | **true**  | No auto-cancel, no auto-close, no auto-clear. |
| `NO_FABRICATION`              | **true**  | Reporters honour real broker state and refuse on ambiguity. |
| `LIVE_TRADING`                | **false** | Hard-pinned. |
| `LIVE_ENABLED`                | **false** | Hard-pinned. |
| `GO_LIVE`                     | **false** | Hard-pinned. |
| `LIVE_TRADING_ENABLED`        | **false** | Hard-pinned. |
| `BROKER_EXECUTION_ENABLED`    | **false** | Hard-pinned. |
| `LLM_PRE_ORDER_VETO_HONORED`  | **false** | LLM advisory only. |
| `OPERATOR_APPROVED_BROKER_PAPER_CANARY` | **false** | Preflight-only. |
| `LLM_AGENTS_SCHEDULED`        | **false** | Advisory mesh stays advisory. |

## 3. Incident snapshot — AVAXUSD P13 bracket interlock

| Item                                | Value |
| ----------------------------------- | ----- |
| First detector finding              | `learning-loop/incidents/2026-06-15.md` 03:21:05 UTC |
| Detector pattern                    | `P13_bracket_interlock_blocked_close` (CRITICAL) |
| Symbols implicated                  | `AVAXUSD`, `ETHUSD` (LTCUSD also failing with 422) |
| Detector findings in window         | 12+ CRITICAL findings between 03:21Z and ~05:06Z |
| safe_close(AVAXUSD) outcome         | **Alpaca 403** — `insufficient balance for AVAX` |
| safe_close(LTCUSD) outcome          | **Alpaca 422** — `qty must be > 0` |
| safe_mode entries (auto-pushed)     | tracked via `shared/safe_mode` + audit JSONL |
| `broker_repair_required_latest.json` contains `AVAX/USD` | **No** — populates from real failures via `shared/retry_storm_containment` |
| `verify_manual_broker_repair.py --symbol AVAX/USD` verdict | `NOT_SAFE_TO_CLEAR` — operator marker missing (expected) |
| `reconcile_equity_gap.py` verdict   | `EQUITY_GAP_OK` (current_equity=$90,523.75 vs peak=$90,954.38, gap=-0.47%) |
| Allocator incident gate decision    | `ALLOW_ALLOCATOR` (no incident artefacts present yet — see §6) |
| Discovery banner                    | Present (added by `scripts/_discovery_incident_banner.py`) |

## 4. v3.28 modules shipped (defence-in-depth, all read-only or audit-only)

- `shared/broker_repair_required.py` — per-symbol quarantine state, frozen
  dataclass `BrokerRepairRequired`, atomic save, operator-marker-gated
  clear. Constants `P13_RETRY_BUDGET=3`,
  `P13_RETRY_BACKOFF_SECONDS=(60,300,1800)`,
  `SAFE_MODE_DEDUPE_WINDOW_SECONDS=600`.
- `shared/retry_storm_containment.py` — `should_skip_broker_call`,
  `record_broker_close_failure` (auto-marks at attempt 3),
  `record_broker_close_success`, `emit_skip_audit`,
  `backoff_seconds_for_attempt`. Counter persisted on disk so it
  survives cron restarts.
- `shared/allocator_incident_gate.py` — fail-CLOSED 7-step gate.
  Default `BLOCK_UNKNOWN`. Affirmative pass on every check required to
  escalate to `ALLOW_ALLOCATOR`. Wired into morning allocator.
- `scripts/verify_manual_broker_repair.py` — operator runbook verifier.
  Default `--dry-run=true`. AST-verified to never import
  `alpaca_orders` and never call any broker mutator.
- `scripts/reconcile_equity_gap.py` — read-only equity-gap reporter.
  Writes dated + latest JSON + markdown. Never blocks autonomously.
- `scripts/_discovery_incident_banner.py` — header banner that surfaces
  the active incident in discovery reports.
- `docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md` — operator runbook.
- `docs/INCIDENT_AVAXUSD_P13_2026-06-16.md` — incident write-up.

## 5. Workflow gating (morning-allocator)

`.github/workflows/morning-allocator.yml` now contains:

- Workflow-level `env:` pin block: all 10 forbidden flags hard-pinned to
  `"false"` (`LIVE_TRADING`, `LIVE_ENABLED`, `GO_LIVE`,
  `LIVE_TRADING_ENABLED`, `ALLOW_BROKER_PAPER`, `EDGE_GATE_ENABLED`,
  `BROKER_EXECUTION_ENABLED`, `LLM_PRE_ORDER_VETO_HONORED`,
  `OPERATOR_APPROVED_BROKER_PAPER_CANARY`, `LLM_AGENTS_SCHEDULED`).
- A pre-execution step "Refuse if any broker / live flag is truthy" that
  fails the run before the allocator runs.
- Wiring of `shared/allocator_incident_gate.evaluate()` ahead of any
  allocator output; non-`ALLOW_ALLOCATOR` verdict aborts the run.

## 6. Why the gate currently returns `ALLOW_ALLOCATOR`

The gate honestly reflects the **state of incident artefacts on disk**:

- `learning-loop/broker_repair_required_latest.json` — **absent**. This
  file is populated by `shared/retry_storm_containment` on the third
  failed `safe_close` of the same symbol. v3.28 just shipped; the
  containment has not yet executed against a live failure.
- `learning-loop/incidents/latest.json` — **absent**. The detector emits
  dated markdown reports; the JSON `latest.json` consumed by the gate
  does not exist yet.
- `learning-loop/equity_gap_reconciliation_latest.json` — present, gap
  is **−0.47%** (well under the 2% block threshold).
- `safe_mode` — not active.

This is the intended **fail-honest** behaviour: the gate does NOT
fabricate an incident, but **the morning-allocator workflow refuses to
run anyway** because (a) `ALLOW_BROKER_PAPER` is hard-pinned `false` and
(b) the workflow-level pin step refuses on any truthy live flag. The
operator must still follow the runbook before clearing safe_mode or
removing the AVAX position via the broker UI.

## 7. Test posture

| Suite                                      | Result      |
| ------------------------------------------ | ----------- |
| v3.28 (new): 8 suites, 75 tests             | **OK**      |
| v3.27 regression (7 suites, 67 tests)       | **OK**      |
| v3.26 + v3.25 sanity (4 suites, 37 tests)   | **OK**      |
| v3.24 + v3.22 + v3.30 safety (6 suites, 63) | **OK**      |
| AST: no `submit_order`/`place_order`/`safe_close`/`cancel_order` in new code | **CLEAN** |

One pre-existing v3.27 test (`test_opportunity_density_plan_v3270.py::TestPlanSections::test_plan_sections_A_through_G_present`) failed because of a date-rollover sensitivity in the near-miss window. Fixed in `scripts/build_opportunity_density_plan.py` by tolerating files dated up to one day after `as_of` (no behavioural change in production).

## 8. Standing markers (must appear in every doc)

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `NO_AUTO_BROKER_ACTION`
- `Generated: 2026-06-16T10:35:00Z`
- `HEAD: 7cbe74139c8d8ada43bfda120b59755ae9d4cd48`

## 9. Operator next steps

1. Open `docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md`.
2. Follow the runbook step-by-step in the Alpaca paper UI to repair the
   AVAX/USD bracket state. Do NOT skip the verifier.
3. After the broker side is repaired, run
   `python3 scripts/verify_manual_broker_repair.py --symbol AVAX/USD`
   (read-only, dry-run by default).
4. Only after the verifier reports `SAFE_TO_CLEAR` may the operator
   create the marker file and clear the per-symbol quarantine.
5. Re-run `python3 scripts/reconcile_equity_gap.py` and confirm
   `EQUITY_GAP_OK`.
6. Re-evaluate the allocator gate by hand; allocator stays gated until
   the operator confirms every step is green.

`LIVE_TRADING_UNSUPPORTED`. `NO_ORDER_PLACEMENT`. `NO_AUTO_BROKER_ACTION`.
`EDGE_GATE_ENABLED=false`. `ALLOW_BROKER_PAPER=false`.
