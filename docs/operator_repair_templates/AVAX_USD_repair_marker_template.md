# Operator repair marker template — AVAX/USD

> **THIS IS A TEMPLATE. Filling this file does NOT count as confirmation.**
>
> The ONLY way to register a real marker is to run:
>
> ```
> python3 scripts/record_operator_repair_confirmation.py \
>     --symbol AVAX/USD --operator-confirmed [--dry-run=false] ...
> ```
>
> Template existence is informational only. Templates live under
> `docs/operator_repair_templates/` or
> `learning-loop/operator_markers/templates/` — these paths are NOT
> scanned for actual markers. The marker scanner only consults files
> directly under `learning-loop/operator_markers/` matching
> `<safe_symbol>_<YYYY-MM-DD>.json` (the suffix `_template.md` /
> `_template.json` is explicitly excluded).

---

## Symbol

- **Canonical:** `AVAX/USD`
- **Aliases:** `AVAX`, `AVAXUSD` (all resolve to the canonical key)
- **Incident type:** `P13_BRACKET_INTERLOCK`

---

## Operator pre-flight checklist (read before filling)

1. Open the Alpaca **paper** dashboard:
   <https://app.alpaca.markets/paper/dashboard/overview>
2. Confirm you are on the PAPER environment, NOT live. The system
   does NOT support live trading.
3. Inspect AVAX/USD position panel: qty, average entry, unrealized P/L.
4. Inspect open-orders panel: any OCO / bracket child / stop / limit
   for AVAX/USD that the autonomous retry path could not unwind.
5. If orphaned legs exist, cancel them manually via the dashboard.
6. If a residual dust position needs closing, do that manually via
   the dashboard.
7. Re-verify final position state + final open-orders state.
8. Capture an equity-after reading.
9. Optional: screenshot the dashboard for audit (link below).

---

## Marker fields to fill (operator writes these into the CLI call)

| Field | What to put | Notes |
|-------|-------------|-------|
| `dashboard_checked` | `true` or `false` | Did you open the dashboard? |
| `open_orders_checked` | `true` or `false` | Did you inspect open orders? |
| `stale_oco_cancelled_by_operator` | `true` / `false` / `unknown` | Did you cancel orphaned legs? |
| `position_closed_by_operator` | `true` / `false` / `unknown` | Did you close the position? |
| `final_position_state` | free text | e.g. `qty=0`, `qty=0.5 dust left intentionally` |
| `final_open_orders_state` | free text | e.g. `none`, `1 LIMIT @ $32 placed by operator` |
| `equity_checked` | `true` or `false` | Did you note final equity? |
| `dashboard_timestamp_utc` | `YYYY-MM-DDThh:mm:ssZ` | When you finished the manual repair |
| `operator_note` | free text | Reason, ticket id, anything useful later |
| `screenshot_reference_optional` | path/URL or empty | Optional dashboard screenshot link |
| `operator_name_optional` | name or initials | Optional |

---

## How to record the real marker

Once you have actually performed the dashboard inspection above,
run (paper only, no live broker call ever):

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
    --operator-note "manually closed AVAX/USD dust + cancelled orphan OCO; ticket #123" \
    --operator-confirmed
```

This writes the real marker file under
`learning-loop/operator_markers/AVAX_USD_<YYYY-MM-DD>.json`. The
record script will refuse to do anything beyond writing that file +
appending one audit row.

After all 3 symbols (AVAX/USD, ETH/USD, LTC/USD) have real markers,
run:

```
python3 scripts/run_operator_clearance_readiness.py
```

to consolidate readiness across symbols, then re-run the system
activation status dashboard.

---

## What this template does NOT do

- It does NOT call the broker.
- It does NOT clear `safe_mode`.
- It does NOT clear `broker_repair_required`.
- It does NOT count as operator confirmation.
- It does NOT enable live trading.
- Sitting on disk filled-in does NOT advance any state.

The marker scanner explicitly ignores `*_template.md` and
`*_template.json` files. Only the CLI invocation above can produce
a real marker.

---

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `NO_AUTO_BROKER_ACTION`
- `NO_AUTO_SAFE_MODE_CLEAR`
- `NO_AUTO_BROKER_REPAIR_CLEAR`
- `TEMPLATE_FILE_DOES_NOT_COUNT_AS_MARKER`
