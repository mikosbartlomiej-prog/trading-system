# Operator Runbook — AVAXUSD P13 bracket-interlock incident (2026-06-16)

> **Audience:** Operator (single human) only.
> **Scope:** Manually repair the AVAXUSD bracket-interlock state in the **Alpaca paper** account, confirm the broker side is consistent, then optionally let v3.28 containment lift the per-symbol quarantine.
> **Status of automated system:** v3.28 containment is engaged. The automated retry path, the morning allocator, and the broker-side close path are all blocked from acting on AVAXUSD without an operator-confirmed marker file. The runbook explains how to perform every step **by hand in the Alpaca paper dashboard**. It does **not** instruct the operator to enable live trading, raise risk limits, or call the broker from this repo.

---

## 1. Situation summary

- **First seen:** 2026-06-15, ~05:46 UTC. Exit-monitor's `safe_close(AVAXUSD)` returned an Alpaca HTTP 403 `insufficient balance for AVAX` while the local position record still showed 365.968010756 AVAX held. The local view of the position and the broker-side balance disagreed.
- **What that means in practice:** at least one open OCO/bracket child order on the broker side was holding the available AVAX balance, so the next "MARKET sell to close" attempt could not be accepted by Alpaca. This is a textbook **bracket interlock** — Layer 1 calls it pattern **P13**.
- **Retry behavior before v3.28:** the exit-monitor kept submitting the same sell-to-close every cron tick, with no backoff, no per-symbol quarantine, and no allocator-side check. By the time it was caught there were 92+ failed safe_close attempts in journal/autonomy.
- **Detector behavior:** `incident_pattern_detector` did fire P13 and called `safe_mode.enter(...)`, but in the previous version of the writer chain those entries did not always make it onto disk in `runtime_state.json::safe_mode`. The allocator then could not "see" safe_mode and continued running. This is the gap v3.28 closes.
- **Status now (v3.28 containment engaged):** AVAXUSD is in the per-symbol quarantine list `learning-loop/broker_repair_required_latest.json`. The retry path **skips** further safe_close attempts. The morning allocator **blocks** on any broker_repair entry. The system is intentionally idle on this symbol until a human operator confirms the broker side is consistent.

This runbook tells the operator:

1. how to read the evidence,
2. how to log into the Alpaca paper dashboard and clean up by hand,
3. how to record that fact on disk,
4. how to ask v3.28 (in read-only mode) whether it is now safe to lift the quarantine.

The runbook never instructs Claude / the automated system to clear safe_mode, cancel orders, or close positions.

---

## 2. Evidence

Before touching anything, read the following files so the manual action below matches reality:

| Path | What it tells you |
|------|-------------------|
| `journal/autonomy/2026-06-15.jsonl` | The 92+ failed `safe_close` entries with `decision: FAILED` and `reason: safe_close: Alpaca 403: ... insufficient balance for AVAX`. Search for `AVAXUSD`. |
| `journal/autonomy/2026-06-16.jsonl` | New entries from v3.28: `REPAIR_REQUIRED_MARK_SET`, `REPAIR_REQUIRED_MARK_UPDATED`, and the `ALLOCATOR_INCIDENT_GATE_DECISION` rows. |
| `learning-loop/broker_repair_required_latest.json` | The on-disk quarantine state. Confirm that `AVAXUSD` (or `AVAX/USD`) is present, with `failed_attempts >= 3`, `incident_type=P13_BRACKET_INTERLOCK` or similar. |
| `learning-loop/runtime_state.json` → `safe_mode` section | The runtime safe_mode flag. After v3.28 this should be `active: true` with `trigger: INCIDENT_P13_BRACKET_INTERLOCK`. |
| `learning-loop/runtime_state.json` → `positions.AVAXUSD` | The local view of the position (qty, opened_at_iso, lifecycle). |
| `learning-loop/incidents/latest.json` | Latest detector finding(s). Confirm P13 finding for AVAXUSD with severity CRITICAL or WARN. |
| `docs/INCIDENT_AVAXUSD_P13_2026-06-16.md` | Post-incident report (see §11). |

If the evidence above does not match the symbol you are actually repairing, **stop**. Do not start the manual repair steps until the evidence is consistent with the situation.

---

## 3. Why the automated system stopped (v3.28 contract)

Three new pieces of code stopped further autonomous broker traffic for AVAXUSD:

1. **`shared/broker_repair_required.py`** — per-symbol quarantine state.
   - When `record_broker_close_failure(symbol, ...)` is called for the 3rd consecutive time it auto-marks the symbol via `mark_repair_required(...)` with `incident_type` carrying the P13 context.
   - `is_repair_required(symbol)` is now checked by the retry path **before** any broker call is made.
   - `clear_repair(symbol, marker_path)` **refuses** to clear unless `marker_path` exists on disk. There is no in-process auto-clear path.

2. **`shared/retry_storm_containment.py`** — retry budget + backoff.
   - `should_skip_broker_call(symbol)` returns `True` whenever the symbol is quarantined, when the retry budget (`P13_RETRY_BUDGET = 3`) is exhausted, or while the backoff window (`P13_RETRY_BACKOFF_SECONDS = (60, 300, 1800)`) has not yet elapsed.
   - The exit-monitor / `safe_close` caller checks this **first**. If `True`, the call is **skipped** and an audit row is emitted.

3. **`shared/allocator_incident_gate.py`** — allocator-side check.
   - `evaluate()` runs at the top of `scripts/execute_allocation_plan.py::main()`.
   - The default verdict is `BLOCK_UNKNOWN`. Only when every single check passes does the verdict escalate to `ALLOW_ALLOCATOR`.
   - On any block: writes `docs/MORNING_ALLOCATOR_BLOCKED_<date>.md`, appends an audit row, and exits cleanly with `return 0`. **No orders are placed.**

`safe_mode` also stays engaged: while `runtime_state.json::safe_mode.active=true` for the P13 trigger, `gate_new_entry()` returns `(False, ...)`, which is honoured by `risk_officer` and `alpaca_orders`.

This is intentional. The automated system has decided it cannot prove that calling the broker again is safe — and it is fail-closed by design.

---

## 4. Manual Alpaca dashboard steps

Perform these steps **only** in the **paper** dashboard. Live trading is unsupported and disabled in this repo.

### 4.1. Log into the paper dashboard

Open: <https://app.alpaca.markets/paper/dashboard/overview>

Confirm:

- The URL contains `/paper/`.
- The account header reads "Paper Account" (NOT "Live Account").

If the URL or header reads "live", stop immediately. Do not continue.

### 4.2. Open Positions and record the current AVAXUSD line

Navigate to **Positions**. Locate **AVAXUSD** (some Alpaca UI screens render it as `AVAX/USD`). Record on paper or a scratch file:

- Symbol (as displayed): _______________
- Side: _______________
- Quantity (as broker sees it): _______________
- Average entry price: _______________
- Current market value: _______________

Compare to `learning-loop/runtime_state.json::positions.AVAXUSD`. The local view at the time of writing was qty `365.968010756` at entry `6.82`. If the broker view differs by more than a trivial rounding amount, write that down — it confirms the interlock.

### 4.3. Open Orders and locate every open AVAXUSD order

Navigate to **Orders** → filter by **AVAXUSD**. Set the filter to include `open`, `accepted`, `new`, `partially_filled`. For each row matching AVAXUSD that is **not** terminal (i.e. NOT `filled`, `canceled`, `rejected`, `expired`), record:

- Order ID: _______________
- Side: _______________
- Type (limit / market / stop / stop_limit): _______________
- Linked parent order ID (if any): _______________
- Status: _______________

Pay particular attention to any OCO group or bracket child orders. These are the orders most likely holding the AVAX balance and causing the 403.

### 4.4. Cancel every open AVAXUSD OCO/bracket child by hand

For each row recorded in §4.3:

- Click the **Cancel** button.
- Confirm the cancellation in the Alpaca confirmation dialog.

Do this one at a time. Do **not** use "Cancel All" — there may be orders on **other** symbols that are healthy and you do not want to disturb. The dashboard's per-row Cancel button is the safest path.

### 4.5. Re-check that AVAXUSD has zero open orders

Reload the **Orders** view, filtered by AVAXUSD with the same status filter from §4.3. The result must show **0 open AVAXUSD orders**. If any open AVAXUSD orders remain, repeat §4.4 for each until the list is empty.

### 4.6. Optional — close the AVAXUSD position by hand

This step is **optional** and should only be performed if the operator has independently decided that closing the AVAXUSD position is the correct action (e.g. because the time-stop verdict from exit-monitor on 2026-06-15 still applies and the operator agrees with it).

If the operator decides closing is correct:

- Navigate to **Positions**.
- Locate **AVAXUSD**.
- Click **Close Position**.
- In the order panel, choose **MARKET** sell-to-close for the full qty (broker side).
- Submit.

Do **not** repeatedly submit close orders. If the first submission fails, wait — do not retry from the dashboard while you still have unresolved open OCO children somewhere in the order book.

### 4.7. Confirm the position view is consistent

After §4.6 (or if you skipped §4.6), refresh **Positions**:

- If you closed: AVAXUSD must not appear in the open positions list.
- If you did not close: AVAXUSD must still be visible at the qty you recorded in §4.2, with **no** open orders against it.

In either case, the state must be **internally consistent**: positions and orders agree, no orphaned OCO child is still pending.

---

## 5. How to confirm safe state

Before doing anything further with this repo, verify, in the Alpaca paper dashboard:

1. **Orders → AVAXUSD → status open/accepted/new/partially_filled:** count must be `0`.
2. **Positions → AVAXUSD:** either absent (if §4.6 was performed) or present at the qty recorded in §4.2 with `held_for_orders == 0` if the column is visible.
3. **Cash + positions reconciles within 0.5%** of the value displayed before §4.4. This is the operator's sanity check that no unexpected order fill happened between §4.3 and §4.7.

If any of (1), (2), or (3) fails, **stop**. Do not create the marker file in §6. Re-read §3 and decide whether to retry §4 or escalate.

---

## 6. How to create the manual repair marker file

The marker file is the on-disk evidence that the operator personally confirmed the broker side is consistent. Without this file, v3.28 refuses to clear the quarantine.

The marker directory and file are **never** auto-created by the system. They are created **only** by the operator, by hand.

From the repo root, run:

```sh
mkdir -p learning-loop/operator_markers/
```

Create `learning-loop/operator_markers/avaxusd_p13_repair_confirmed_2026-06-16.txt` with the following contents (substitute the bracketed fields):

```
operator_name:    [your name]
confirmation_iso: [UTC timestamp YYYY-MM-DDThh:mm:ss+00:00]
symbol:           AVAX/USD
broker_account:   paper
checked_orders_open_count: 0
checked_positions_consistent: true
manual_close_performed: [true|false]
note: [optional 1-line summary]
```

Do **not** commit `learning-loop/operator_markers/` to git. It is operator-local state and is excluded from version control. (If you accidentally commit it, treat that as an audit-trail leak and remove the commit.)

---

## 7. How to run the read-only verification script

The verification script is `scripts/verify_manual_broker_repair.py`. It is **read-only by default** (`--dry-run=true`). It never calls the broker, never imports `alpaca_orders`, never makes network calls, and never actually clears safe_mode.

Run:

```sh
python3 scripts/verify_manual_broker_repair.py \
    --symbol AVAX/USD \
    --marker-path learning-loop/operator_markers/avaxusd_p13_repair_confirmed_2026-06-16.txt
```

Expected verdict in this scenario: **`SAFE_TO_CLEAR_CANDIDATE`** with reasons that include "marker present", "no broker call attempted", and a summary of the on-disk evidence the script consulted.

Possible alternative verdicts:

- `NOT_SAFE_TO_CLEAR` — printed when any precondition fails (marker missing, equity-gap unresolved, position reconciliation report missing or stale, opportunity ledger still showing live failures, etc.). The verdict line includes the reason.

Whichever verdict you see, an audit row is appended to `journal/autonomy/<date>.jsonl` describing the run.

---

## 8. How to safely propose clearing safe_mode

Even when the verdict is `SAFE_TO_CLEAR_CANDIDATE`, the script **does not** clear safe_mode. It can only write a **proposal** file. The operator (not Claude, not any script) then takes the final action.

To write the proposal, re-run with `--operator-confirmed --dry-run=false`:

```sh
python3 scripts/verify_manual_broker_repair.py \
    --symbol AVAX/USD \
    --marker-path learning-loop/operator_markers/avaxusd_p13_repair_confirmed_2026-06-16.txt \
    --operator-confirmed \
    --dry-run=false
```

If the verdict is still `SAFE_TO_CLEAR_CANDIDATE`, the script writes:

```
learning-loop/operator_markers/safe_mode_clear_proposal_<date>.json
```

and prints the verdict `SAFE_MODE_CLEAR_PROPOSED_OPERATOR_MUST_APPLY`. The script then exits.

What this means in practice:

- The script has **not** flipped `runtime_state.json::safe_mode.active=false`.
- The script has **not** cleared `broker_repair_required_latest.json::AVAXUSD`.
- The script has **not** enabled `LIVE_TRADING`, `ALLOW_BROKER_PAPER`, `EDGE_GATE_ENABLED`, or `BROKER_EXECUTION_ENABLED`. These remain off.
- The script has **not** auto-cancelled any broker order or closed any position.

The proposal file is informational. The operator decides whether to act on it. Acting on it is a manual operator step — outside the scope of the script and outside the scope of this runbook (which is intentional).

If you decide to clear the quarantine, do it in this order:

1. Re-read §5 and re-verify that the broker side is still consistent (orders 0, positions stable).
2. Use `shared/broker_repair_required.py::clear_repair(symbol, marker_path)` from a short Python REPL invocation (operator-driven). The function refuses unless the marker file is present and emits a `REPAIR_REQUIRED_CLEARED` audit row.
3. Confirm `learning-loop/broker_repair_required_latest.json` no longer contains AVAXUSD.
4. Leave `safe_mode.active=true` until the underlying trigger (P13 today) has cleared from `learning-loop/incidents/latest.json`. The standard `safe_mode.exit_safe_mode()` path runs from monitors when conditions are clear — do not force it.

---

## 9. How to restart the allocator after repair

Once the quarantine is lifted and safe_mode has naturally returned to inactive:

1. **Dry-run first.** Trigger `scripts/execute_allocation_plan.py` with the existing date's plan. Expected outcome: `ALLOW_ALLOCATOR` from the gate. If the plan is empty or stale, the allocator will exit with no orders (this is correct).
2. **Watch the next scheduled cron tick.** Confirm that morning-allocator now passes the gate and (if there is a plan to execute) emits orders through the normal path.
3. **Tail `journal/autonomy/<date>.jsonl`** for `ALLOCATOR_INCIDENT_GATE_DECISION` rows with `decision: ALLOW_ALLOCATOR` followed by the usual order audit rows.

If the gate still blocks after repair, **do not bypass it**. Re-read the snapshot in the block audit row — there is another blocker that must be resolved first (equity-gap, kill-switch, P13 finding from today still present, etc.).

---

## 10. What NOT to do

The following actions are explicitly forbidden during P13 incident response in this repo. They are listed here so that any future Claude session reading this runbook sees them in plain text:

10.1. **Do NOT force `safe_mode = false` blindly.** Editing `runtime_state.json::safe_mode.active` by hand bypasses every downstream gate and re-opens the same broker traffic that caused the storm. If you must clear it, follow §8 and let the operator-driven path do it.

10.2. **Do NOT retry `safe_close` while any AVAXUSD OCO is open on the broker.** That is exactly what produced 92+ failed attempts on 2026-06-15. v3.28 will skip the call anyway — do not write code that bypasses `should_skip_broker_call`.

10.3. **Do NOT run the allocator with an unresolved P13.** v3.28 will block it; do not edit the gate to make it ALLOW. The default `BLOCK_UNKNOWN` exists for this reason.

10.4. **Do NOT enable any of these flags** (read by `shared/runtime_config.py` and asserted by `assert_paper_only`):
- `LIVE_TRADING`
- `LIVE_ENABLED`
- `GO_LIVE`
- `LIVE_TRADING_ENABLED`
- `ALLOW_BROKER_PAPER`
- `EDGE_GATE_ENABLED`
- `BROKER_EXECUTION_ENABLED`
- `LLM_PRE_ORDER_VETO_HONORED`
- `OPERATOR_APPROVED_BROKER_PAPER_CANARY`
- `LLM_AGENTS_SCHEDULED`

10.5. **Do NOT delete the `broker_repair_required` entry directly** (e.g. by editing the JSON). The clear path goes through `clear_repair(symbol, marker_path)` so that an audit row is emitted. Editing the file by hand defeats the audit trail.

10.6. **Do NOT add paid APIs, new monitors, or LLM calls to the runtime trading path** as part of "fixing" this incident. The fix is operator-driven, on-disk-only, and budget-neutral.

10.7. **Do NOT commit `learning-loop/operator_markers/`**. It is operator-local. Commit only the runbook, the verification script, and the post-incident report.

10.8. **Do NOT force-push** during incident response. Force-push obliterates the audit trail.

---

## 11. Post-repair verification checklist

After §9 has shown a clean cycle:

- [ ] `learning-loop/broker_repair_required_latest.json` does not contain AVAXUSD (or any symbol).
- [ ] `runtime_state.json::safe_mode.active=false` and `forced=false`.
- [ ] `learning-loop/incidents/latest.json` no longer carries an active P13 finding for AVAXUSD.
- [ ] `journal/autonomy/<today>.jsonl` contains:
  - `REPAIR_REQUIRED_CLEARED` for AVAXUSD,
  - `SAFE_MODE_EXITED` from the natural exit path,
  - `ALLOCATOR_INCIDENT_GATE_DECISION` with `decision: ALLOW_ALLOCATOR`.
- [ ] Position reconciliation report shows AVAXUSD in the state the operator confirmed (either absent or at the recorded qty with zero `held_for_orders`).
- [ ] Equity gap reconciliation report shows verdict `EQUITY_GAP_OK` (gap < 0.5%) or at worst `EQUITY_GAP_WARN` (0.5%–2%). It must **not** be `EQUITY_GAP_UNRESOLVED_BLOCKS_ALLOCATOR`.
- [ ] The 2026-06-16 incident report (`docs/INCIDENT_AVAXUSD_P13_2026-06-16.md`) has been updated with the "Resolution" section so future operators have the closing summary.

---

## Footer — standing markers (do not remove)

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `NO_AUTO_BROKER_ACTION_FROM_THIS_RUNBOOK`
