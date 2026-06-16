# Operator Repair Confirmation — operator-side manual quarantine clear

**Module:** `shared/operator_repair_state.py`
**CLI:** `scripts/record_operator_repair_confirmation.py`
**Version:** v3.29 ETAP 1 (2026-06-16)

---

## Purpose

When `shared/broker_repair_required.py` quarantines a symbol after the
P13 retry budget is exhausted, the only way out is a *human operator*
who:

1. Opened the Alpaca dashboard (or paper trading UI),
2. Verified the actual broker-side state for the affected symbol,
3. Manually cancelled any orphaned OCO legs and/or closed the dust
   position,
4. Confirmed the final position and open-orders state with their own
   eyes.

This module owns the data structure that records that confirmation.
It is the canonical "I, the operator, looked at the broker UI, did
the work, and take responsibility" marker.

The marker file is read by `shared/broker_repair_required.clear_repair`,
by `shared/allocator_incident_gate`, and by reporting scripts. None of
those consumers ever creates a marker on their own.

---

## When to use

You should run this script ONLY after you have:

* manually checked the Alpaca dashboard for the affected symbol,
* cancelled any orphaned OCO/stop/limit legs that the autonomous
  retry path could not unwind,
* confirmed (looking at the dashboard) what the final position
  state is (qty = 0 / qty = X with a fresh exit plan),
* confirmed (looking at the dashboard) what the final open-orders
  state is (none / N orders queued by you intentionally),
* recorded enough operator notes that a future you can audit what
  actually happened.

**Do not** run this script speculatively or "to try it out". The
marker is a load-bearing artefact: once written, it lets the rest
of the system act as if a human has resolved the incident.

---

## CLI usage examples

### Dry run (default)

```
python3 scripts/record_operator_repair_confirmation.py \
    --symbol AVAXUSD \
    --incident-type P13_BRACKET_INTERLOCK \
    --dashboard-checked \
    --open-orders-checked \
    --stale-oco-cancelled true \
    --position-closed true \
    --equity-checked \
    --operator-note "manually closed stuck AVAX dust + cancelled orphan OCO at 12:14 UTC"
```

Without `--operator-confirmed`, the script prints the payload it
*would* write and exits 0. Nothing is persisted.

### Actually write the marker

```
python3 scripts/record_operator_repair_confirmation.py \
    --symbol AVAXUSD \
    --incident-type P13_BRACKET_INTERLOCK \
    --dashboard-checked \
    --open-orders-checked \
    --stale-oco-cancelled true \
    --position-closed true \
    --equity-checked \
    --operator-note "manually closed stuck AVAX dust + cancelled orphan OCO at 12:14 UTC" \
    --operator-confirmed
```

This writes
`learning-loop/operator_markers/AVAXUSD_<YYYY-MM-DD>.json`
and appends one audit JSONL row.

### Forced dry-run

```
python3 scripts/record_operator_repair_confirmation.py \
    --symbol AVAXUSD \
    --operator-confirmed \
    --dry-run true
```

`--dry-run true` always wins. Use this when you want to preview the
payload while keeping `--operator-confirmed` enabled in a shell
history.

---

## Marker schema

The on-disk JSON contains:

| Field | Type | Notes |
|-------|------|-------|
| `symbol` | string | Required. Symbol that was quarantined. |
| `incident_type` | string | E.g. `P13_BRACKET_INTERLOCK`. |
| `dashboard_checked` | bool | Operator confirms dashboard inspection. |
| `open_orders_checked` | bool | Operator confirms open-orders inspection. |
| `stale_oco_cancelled_by_operator` | `"true"`/`"false"`/`"unknown"` | Tri-state on cancel. |
| `position_closed_by_operator` | `"true"`/`"false"`/`"unknown"` | Tri-state on close. |
| `final_position_state` | string | Free-form note. |
| `final_open_orders_state` | string | Free-form note. |
| `equity_checked` | bool | Operator confirms equity check. |
| `operator_note` | string | Free-form operator note. |
| `timestamp_iso` | string | UTC ISO-8601 timestamp. Required. |
| `source` | constant | Always `"OPERATOR_MANUAL_CONFIRMATION"`. |
| `does_not_execute_orders` | constant | Always `true`. |

Both `source` and `does_not_execute_orders` are forced by
`operator_repair_state._normalize` before persistence. Callers
cannot override them.

---

## What this module / script does NOT do

* It does **not** call the broker.
* It does **not** import `alpaca_orders`.
* It does **not** clear `safe_mode`.
* It does **not** call
  `shared.broker_repair_required.clear_repair`.
* It does **not** flip `LIVE_TRADING`, `ALLOW_BROKER_PAPER`, or
  `EDGE_GATE_ENABLED`.
* It does **not** place, cancel, or modify orders.
* It does **not** mutate any risk threshold.
* It does **not** auto-deploy capital.

The marker is *evidence*. Quarantine clears, safe_mode exits, and
allocator deployments are all separate decisions made by other
modules that consult the marker.

---

## Integration with the allocator gate

`shared/allocator_incident_gate.py` already reads
`shared/broker_repair_required.get_blocked_symbols()`. When a marker
exists for a quarantined symbol AND
`shared/broker_repair_required.clear_repair(symbol, marker_path)`
has been invoked, the symbol leaves `get_blocked_symbols()`. The
allocator's `BLOCK_BROKER_REPAIR_REQUIRED` gate then stops firing
for that symbol on the next evaluation.

Backfill (see
`scripts/backfill_broker_repair_from_incidents.py` and v3.29 ETAP 3)
respects markers: if a marker exists for a symbol on a given day,
the backfiller will **not** mark that symbol as repair-required
for that day. Operator confirmation is the single source of truth
for "this was already resolved manually".

---

## Operational checklist

When the system emails you a quarantine alert:

1. Open the Alpaca dashboard for the affected symbol.
2. Verify open orders. Cancel any orphan OCO / stop / limit legs that
   the system could not unwind. Note them down.
3. Verify position. Close the residual dust if needed.
4. Verify the resulting equity reading.
5. Run the CLI above with `--operator-confirmed` and your operator
   note describing what you did.
6. Manually clear the quarantine via the dedicated helper (this is
   the only path that consults the marker on disk).

---

## Standing markers

These are repeated on every payload, every doc, every audit row.
They exist to make it obvious that this entire pathway is offline,
read-only, and paper-only:

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE`

---

## v3.31 — Per-symbol templates + end-to-end clearance flow

v3.31 ships paper-only templates for each canonical repair symbol
plus a consolidated readiness wrapper. The templates are advisory;
they do NOT advance any state on their own.

### Template locations (NOT scanned as real markers)

- `docs/operator_repair_templates/<safe_symbol>_repair_marker_template.md`
- `learning-loop/operator_markers/templates/<safe_symbol>_repair_marker_template.json`

Where `<safe_symbol>` substitutes `/` → `_` (e.g. `AVAX_USD`).

The marker scanner in `shared/operator_repair_state.py` ONLY reads
files directly under `learning-loop/operator_markers/` matching
`<safe_symbol>_<YYYY-MM-DD>.json`. Anything under a `templates/`
subdirectory or named with the `_template.md` / `_template.json`
suffix is explicitly ignored.

### End-to-end operator checklist (v3.31)

This is the canonical step-by-step the operator follows when a
quarantine alert lands. Every step is paper-only; never live.

1. Open the Alpaca **paper** dashboard at
   <https://app.alpaca.markets/paper/dashboard/overview>
   (paper only — the system explicitly does NOT support live).
2. For each canonical repair symbol — currently `AVAX/USD`,
   `ETH/USD`, `LTC/USD` — inspect:
   - position panel (qty, avg entry, unrealized P/L)
   - open-orders panel (any OCO / bracket child / stop / limit)
3. Cancel any orphaned OCO / bracket-child legs that the
   autonomous retry path could not unwind.
4. Decide whether the residual position should be closed manually
   (a paper-side flat) or left intentionally.
5. Verify the final position state and final open-orders state
   with your own eyes from the dashboard.
6. For each symbol you actually inspected, copy the template from
   `docs/operator_repair_templates/<safe_symbol>_repair_marker_template.md`
   (read-only — do NOT edit the template file in place; it is just
   a reference for what to put in the CLI call), then run:

   ```
   python3 scripts/record_operator_repair_confirmation.py \
       --symbol AVAX/USD \
       --incident-type P13_BRACKET_INTERLOCK \
       --dashboard-checked \
       --open-orders-checked \
       --stale-oco-cancelled true \
       --position-closed true \
       --final-position-state "qty=0 confirmed at 14:02 UTC" \
       --final-open-orders-state "none confirmed at 14:02 UTC" \
       --equity-checked \
       --operator-note "manually closed AVAX/USD dust + cancelled orphan OCO" \
       --operator-confirmed
   ```

   This is the ONLY path that writes a real marker. Repeat for
   `ETH/USD` and `LTC/USD` separately.

7. Once markers exist for ALL 3 canonical repair symbols, run the
   v3.31 consolidated readiness wrapper:

   ```
   python3 scripts/run_operator_clearance_readiness.py
   ```

   With no flags it defaults to dry-run. It validates per-symbol
   that the marker exists, that no fresh P13 / retry-storm event
   landed after the marker, that the safe-mode-consistency verdict
   is `CONSISTENT` (not `INCONSISTENT_ENTERED_NOT_PERSISTED`),
   that the equity-gap report does NOT block, and that the
   broker-repair entry is still active (i.e. there is something to
   clear).

   Possible per-symbol / overall verdicts:
   - `NOT_READY_NO_MARKER`
   - `NOT_READY_FRESH_P13_AFTER_MARKER`
   - `NOT_READY_SAFE_MODE_INCONSISTENT`
   - `NOT_READY_EQUITY_GAP`
   - `NOT_READY_BROKER_REPAIR_STILL_ACTIVE`
   - `READY_TO_PROPOSE_CLEARANCE` (dry-run stops here)
   - `CLEARANCE_PROPOSAL_WRITTEN` (only with
     `--apply --operator-confirmed`)
   - `READY_FOR_OPERATOR_MANUAL_APPLY`

8. If you choose to materialize a proposal (still write-only;
   does NOT clear safe_mode or broker_repair_required), run:

   ```
   python3 scripts/run_operator_clearance_readiness.py \
       --apply --operator-confirmed
   ```

   The wrapper delegates each READY symbol to
   `scripts/propose_clear_broker_repair_and_safe_mode.py`. That
   script never auto-clears anything either — it only writes a
   proposal JSON for operator review.

9. Finally, re-run the dashboard / `system_activation_status`
   build (`scripts/build_system_activation_status.py`) to confirm
   that the activation gate's blocker list reflects reality.

### What this flow still does NOT do

- It does NOT call the broker.
- It does NOT import `alpaca_orders`.
- It does NOT clear `safe_mode`.
- It does NOT clear `broker_repair_required` automatically.
- It does NOT flip `LIVE_TRADING` / `ALLOW_BROKER_PAPER` /
  `EDGE_GATE_ENABLED`.
- It does NOT place, cancel, or modify orders.
- Filling a template file does NOT count as confirmation.

`run_operator_clearance_readiness.py` is fail-closed. If anything
is unclear it returns `NOT_READY_*` and refuses to write a
proposal even with `--operator-confirmed`. Live remains
unsupported.

