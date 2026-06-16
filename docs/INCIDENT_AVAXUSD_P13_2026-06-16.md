# Incident Report — AVAXUSD P13 bracket-interlock storm (2026-06-15 → 2026-06-16)

**Status:** Containment shipped (v3.28). Manual broker repair still required by operator. System remains paper-only, EDGE_GATE_ENABLED=false, ALLOW_BROKER_PAPER=false, LIVE_TRADING_UNSUPPORTED. No live trading was enabled, attempted, or proposed during the incident or its response.

---

## 1. Summary

On 2026-06-15, starting at ~05:46 UTC, the exit-monitor's `safe_close(AVAXUSD)` retry path entered an unbounded loop against the Alpaca paper crypto endpoint. Every attempt returned HTTP 403 `insufficient balance for AVAX (request 365.968010756, available 365.968010756, balance 365.968010756)`. The local position record showed the full qty as available, but at least one open OCO/bracket child order on the broker side was holding the available balance, so the sell-to-close could not be accepted.

By the end of the day there were 92+ identical FAILED `safe_close` audit rows for AVAXUSD with no backoff, no per-symbol quarantine, and no allocator-side check. The `incident_pattern_detector` did call `safe_mode.enter(...)` with the P13 trigger, but in the writer chain in effect at the time, the safe_mode flag did not always make it onto disk in `runtime_state.json::safe_mode`. The allocator's read path therefore saw safe_mode as inactive and remained free to deploy fresh capital.

This is the same class of incident as the May 2026 events that produced the v3.11.3 + v3.13 fixes, but those fixes only stopped one specific code path (bracket OCO cancel-before-close); they did not contain the retry storm itself when the cancel-and-close pattern still failed at the broker. v3.28 fixes that gap.

## 2. Timeline (UTC)

- **2026-06-13 02:35** — AVAXUSD position opened at $6.82, qty 365.968010756, swing intent. Bracket OCO children placed alongside.
- **2026-06-15 ~02:00** — Exit-monitor's `time_stop` evaluation tripped for AVAXUSD. The lifecycle moved to `TIME_EXPIRED`. The cron loop began calling `safe_close(AVAXUSD)`.
- **2026-06-15 05:46** — First Alpaca 403 `insufficient balance for AVAX`. No backoff path. No per-symbol cooldown. The next cron tick retried.
- **2026-06-15 06:00 → 15:21** — Continuous retries. Every */5 cron tick produced one or more `safe_close` FAILED rows for AVAXUSD. Final count was 92+ identical failures.
- **2026-06-15 — incident-pattern-detector P13** — fired multiple times. Called `safe_mode.enter(trigger="INCIDENT_P13_BRACKET_INTERLOCK", ...)`. Some attempts did persist to `runtime_state.json::safe_mode`, some did not (writer ordering bug, see §4 root cause #2). Either way, the allocator did not see safe_mode reliably.
- **2026-06-15 — allocator** — every morning-allocator cron tick during the day re-ran with no incident gate at the top, only the per-symbol checks inside `place_*` paths. The downstream paths refused to BUY into AVAXUSD specifically, but the allocator was free to deploy fresh capital on other symbols, which is exactly what the operator wanted blocked.
- **2026-06-16** — Containment shipped: `broker_repair_required` + `retry_storm_containment` + `allocator_incident_gate` + `verify_manual_broker_repair` + `reconcile_equity_gap`. Runbook published. AVAXUSD entered the per-symbol quarantine. The morning allocator is blocked. The retry path is blocked. Operator-side repair pending.

## 3. Root-cause hypothesis

Three independent gaps. v3.28 closes all three but does not by itself repair the broker side — that step is operator-driven and described in `docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md`.

### 3.1. No per-symbol quarantine for "broker said no, repeatedly"

The exit-monitor's `safe_close` path had no notion of "this symbol is broken; stop calling the broker for it". The only braking mechanism was the broader safe_mode flag, which (a) did not always persist (see §3.2), and (b) blocks new entries but does NOT stop the exit-monitor from re-trying closes — by design, since closing positions is normally exactly what safe_mode wants.

**Fix in v3.28:** `shared/broker_repair_required.py` is a per-symbol "do not autonomously call broker for this symbol" state, orthogonal to safe_mode. It is checked by `should_skip_broker_call(symbol)` BEFORE every broker close attempt. The 3rd consecutive failure auto-marks the symbol via `mark_repair_required(...)`. Operator-only clear path via `clear_repair(symbol, marker_path)`, which refuses unless an operator marker file is present on disk.

### 3.2. safe_mode writer ordering

The `incident_pattern_detector` called `safe_mode.enter(...)` but the writer chain (already in v3.22 ETAP 9) interleaved with other writers to `runtime_state.json`. Under load, the safe_mode section was sometimes overwritten by a concurrent monitor's write that did not carry the safe_mode field. The allocator then read `safe_mode.active=false` and continued.

**Fix in v3.28:** The fix is structural in v3.28's allocator-side check: `allocator_incident_gate.evaluate()` does not solely rely on safe_mode. It checks safe_mode AND `broker_repair_required` AND the incident-detector's latest payload AND the equity-gap reconciliation AND position-reconciliation freshness AND kill-switch. Default verdict is `BLOCK_UNKNOWN`. Only when EVERY check passes does it escalate to `ALLOW_ALLOCATOR`. This is fail-closed — any check raising → BLOCK_UNKNOWN.

The safe_mode writer ordering issue is **not** structurally fixed in v3.28 — the dedupe window contract from v3.22 ETAP 9 still applies. v3.28 makes the allocator robust against the safe_mode flag temporarily disappearing. The safe_mode writer ordering is a P2 backlog follow-up.

### 3.3. No allocator-side gate at the top of `execute_allocation_plan.main()`

The morning allocator opened the plan file, set up clients, and only checked safe_mode inside the per-order code path (via `risk_officer` → `safe_mode.gate_new_entry`). That gate worked for individual BUYs but did not stop the allocator from importing modules, fetching state, or running the planner — and crucially it does not prevent the allocator from deploying capital on **other** symbols while a single symbol is in the bracket-interlock state.

**Fix in v3.28:** `scripts/execute_allocation_plan.py::main()` runs `allocator_incident_gate.evaluate()` FIRST, before plan-file lookup, before allocator import, and before any order construction. On BLOCK it writes `docs/MORNING_ALLOCATOR_BLOCKED_<date>.md`, appends an audit row, and exits cleanly with `return 0`. No orders are placed. Operator reads the block doc to understand why.

## 4. Failed assumptions

- **"safe_mode persists reliably."** It did not, under cron-induced write contention. v3.28 does not require safe_mode persistence at the allocator entry point — multiple independent gates must pass.
- **"P13 fix from v3.11.3 covered the bracket-interlock class."** It only covered the cancel-before-close pattern. When the cancel itself fails (or when the broker side has orphan OCO children that this repo did not place), the v3.11.3 fix does not stop the retry storm. v3.28 adds the per-symbol quarantine to stop the retry storm.
- **"Exit-monitor retries are cheap."** They produced 92+ identical FAILED audit rows, polluting the journal and obscuring other decisions. The 3-attempt budget + 60s/300s/1800s backoff schedule (v3.28) makes them bounded and visible.

## 5. Why the previous P13 fix was insufficient

The 2026-05-29 v3.10/v3.11.3 P13 work centralised broker close calls through `safe_close()` and added invariants (cancel OCO before close; AST lint rejecting any new `requests.post(/v2/orders ...)` outside the allowlist). Those invariants are still active and were not violated on 2026-06-15. What the v3.10/v3.11.3 fixes did NOT cover:

- They assumed that the cancel step inside `safe_close` would itself succeed. On 2026-06-15 the broker side held orphan OCO children that this repo did not place (or did place earlier but did not record the parent ID locally). The cancel step inside `safe_close` therefore did not know what to cancel, and the subsequent sell-to-close hit the 403.
- They did not add a retry budget at the call-site. v3.11.3 ensured the cancel-then-close pattern is the only path, but did not bound how many times the pattern could repeat per symbol per day.
- They did not add an allocator-side gate. The morning allocator could still deploy fresh capital while a single symbol was in a retry storm.

v3.28 explicitly adds the budget (v3.28 ETAP 5), the per-symbol quarantine (ETAP 4), the allocator gate (ETAP 3+8), the verification tool (ETAP 6), and the equity reconciliation (ETAP 7).

## 6. What v3.28 prevents vs what was already broken

| Item | v3.28 prevents? | Notes |
|------|-----------------|-------|
| Future infinite retry storms on a single symbol | Yes | Retry budget = 3, backoff 60s/300s/1800s. After 3rd failure: quarantine. |
| Allocator deploying capital during an active P13 | Yes | `allocator_incident_gate` default `BLOCK_UNKNOWN`. |
| Operator silently missing the incident | Yes | `docs/MORNING_ALLOCATOR_BLOCKED_<date>.md` is written on every block. |
| Audit-rolling JSONL spam from the retry path | Yes | After quarantine, `should_skip_broker_call` emits a single skip row per attempt instead of a FAILED order row. |
| The 2026-06-15 broker-side state (open OCO children holding AVAX) | **No.** | This requires a manual operator step in the Alpaca paper dashboard — see `docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md`. v3.28 does not auto-cancel broker orders. |
| Live-trading exposure | N/A | EDGE_GATE_ENABLED=false, ALLOW_BROKER_PAPER=false, LIVE_TRADING_UNSUPPORTED. None of these flipped during the incident or its response. |
| Operator-driven safe_mode clear | Yes | `verify_manual_broker_repair.py` is read-only by default; even with `--operator-confirmed --dry-run=false` it only writes a **proposal** file. The actual clear remains an operator action via `broker_repair_required.clear_repair(symbol, marker_path)`. |

## 7. Manual action required

See `docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md` for the step-by-step operator runbook. Summary:

1. Log into the Alpaca **paper** dashboard.
2. Cancel every open AVAXUSD OCO/bracket child by hand.
3. Optionally close the AVAXUSD position with a MARKET sell-to-close (operator's call).
4. Confirm broker-side state is consistent.
5. Create the marker file `learning-loop/operator_markers/avaxusd_p13_repair_confirmed_2026-06-16.txt`.
6. Run `scripts/verify_manual_broker_repair.py --symbol AVAX/USD --marker-path <path>` in default (read-only) mode and read the verdict.
7. Optionally rerun with `--operator-confirmed --dry-run=false` to write a clear proposal.
8. Manually clear the quarantine via `broker_repair_required.clear_repair(symbol, marker_path)`.

## 8. Code changes (v3.28)

- New: `shared/broker_repair_required.py` (per-symbol quarantine state, frozen dataclass, atomic save_state, operator-marker-gated clear).
- New: `shared/retry_storm_containment.py` (retry budget = 3, backoff 60s/300s/1800s, auto-mark after 3rd failure, audit skip emission).
- New: `shared/allocator_incident_gate.py` (default `BLOCK_UNKNOWN`, 6 ordered checks, fail-CLOSED on any exception).
- New: `scripts/verify_manual_broker_repair.py` (read-only default, dry-run default true, never calls broker, never imports `alpaca_orders`, never auto-clears safe_mode).
- New: `scripts/reconcile_equity_gap.py` (read-only equity decomposition, writes JSON + Markdown report, NEVER changes threshold or calls broker).
- New docs: this file, the runbook, and a daily equity-gap markdown.
- Edited: `scripts/execute_allocation_plan.py::main()` — incident gate evaluated FIRST, before plan-file lookup or allocator import. `_write_block_doc()` helper writes `docs/MORNING_ALLOCATOR_BLOCKED_<date>.md`.
- Edited: `exit-monitor/monitor.py` — `should_skip_broker_call(symbol)` precondition before `_safe_close`, `record_broker_close_failure` / `record_broker_close_success` after attempt. Fail-soft on helper-import error.
- Existing `shared/safe_mode.py` (v3.22 ETAP 9) already accepts `dedupe_seconds=INCIDENT_DEDUPE_WINDOW_SECONDS`; not modified.

## 9. Tests added

- `tests/test_broker_repair_required_v3280.py` — 12 cases (state persistence, atomic write, marker-gated clear, audit emission, frozen dataclass).
- `tests/test_retry_storm_containment_v3280.py` — 10 cases (budget exhaustion, backoff windows, auto-mark on 3rd failure, success resets, audit skip rows).
- `tests/test_allocator_incident_gate_v3280.py` — 14 cases (default BLOCK_UNKNOWN, each blocker triggers the correct verdict, fail-CLOSED on exception, ALLOW_ALLOCATOR only on full-pass).
- `tests/test_runbook_avax_v3280.py` — 6 cases (this file + runbook exist, paper account URL present, no live-trading recommendation, what-not-to-do section, standing markers, verify-script reference).
- `tests/test_verify_manual_broker_repair_v3280.py` — 10 cases (dry-run default true, default verdict NOT_SAFE_TO_CLEAR on error, marker required, --operator-confirmed required to write proposal, writes proposal not clear action, AST: no broker call, AST: no `alpaca_orders` import, never clears safe_mode, audit row per run).
- `tests/test_equity_gap_reconcile_v3280.py` — 8 cases (writes JSON, > 2% → BLOCKS_ALLOCATOR, 0.5–2% → WARN, < 0.5% → OK, missing inputs handled, no broker call, no threshold change, standing markers present).

All passing in this session.

## 10. Residual risks

- **Broker-side OCO orphans on other symbols.** The 2026-06-15 event was AVAXUSD-only. If another symbol enters the same broker-side state, v3.28 will quarantine it cleanly, but the same operator runbook (cancel by hand) must be performed for that symbol. The runbook is symbol-specific; the next operator may need to write a sibling runbook with the same structure but a different symbol.
- **safe_mode writer ordering** (root cause §3.2). v3.28 is robust against this at the allocator entry point, but the writer ordering itself is unresolved. v3.29 backlog: serialise writes to `runtime_state.json` so safe_mode cannot be silently overwritten.
- **Equity reconciliation depends on dashboard snapshot.** When the dashboard snapshot is missing or stale, `reconcile_equity_gap.py` falls back to the runtime_state view and absorbs any discrepancy into the `unexplained` component. The verdict is still computed off `gap_pct` against `peak_equity`, so the BLOCK threshold still bites.
- **Per-symbol quarantine is operator-only to clear.** This is by design. Operators who do not have shell access to the repo cannot clear it. The "operator marker file" path is the explicit clearance mechanism.

## 11. Next verification checklist

- [ ] Operator has read `docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md` end-to-end.
- [ ] Operator has confirmed the dashboard URL contains `/paper/` and the account header reads "Paper Account".
- [ ] Operator has cancelled every open AVAXUSD OCO/bracket child by hand.
- [ ] Operator has decided whether to close the position by MARKET sell-to-close (or to leave it open).
- [ ] Operator has created the marker file `learning-loop/operator_markers/avaxusd_p13_repair_confirmed_2026-06-16.txt`.
- [ ] `python3 scripts/verify_manual_broker_repair.py --symbol AVAX/USD --marker-path <path>` returns `SAFE_TO_CLEAR_CANDIDATE`.
- [ ] `python3 scripts/reconcile_equity_gap.py` returns `EQUITY_GAP_OK` (or at worst `EQUITY_GAP_WARN`).
- [ ] Operator has cleared the quarantine via `broker_repair_required.clear_repair(symbol, marker_path)`.
- [ ] Allocator runs through the gate with `ALLOW_ALLOCATOR` on the next cron tick.
- [ ] First post-incident audit row of `decision: ALLOW_ALLOCATOR` is visible in `journal/autonomy/<date>.jsonl`.

---

## Standing markers (do not remove)

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `NO_AUTO_BROKER_ACTION_FROM_THIS_REPORT`
