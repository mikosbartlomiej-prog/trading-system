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
