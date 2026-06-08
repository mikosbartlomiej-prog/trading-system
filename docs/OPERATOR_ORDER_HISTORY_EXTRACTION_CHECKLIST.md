# Operator Order History Extraction Checklist (v3.23.2)

This checklist is the input needed to close the **2026-06-04 incident
reconciliation gap**. AMD has already been reconstructed from
operator-provided manual order history (see
`learning-loop/position_reconciliation/manual_order_history_AMD_2026-06-04.json`,
realized P/L `-$437.07`). The remaining ~$5,304 of the -$5,741
baseline drop is unexplained until the operator transcribes order
history for these 7 symbols.

## Required Alpaca Order History Extraction

**Account:** Alpaca Paper (per CLAUDE.md reference, account `PA3KNZV29BP5`).
**Source:** Dashboard "Order History" view at
`app.alpaca.markets/paper/dashboard` → Activity → Orders.
**Symbols:**

- CRWD
- NOW
- QQQ
- SPY
- GLD
- PANW
- ORCL

**Time window:** 2026-06-04 13:45 UTC (allocator BUY batch) through
2026-06-05 18:00 UTC (close cycle should be complete by then).

## Per-symbol fields to capture (one BUY + one SELL row per symbol)

For each symbol, transcribe both the BUY/open row and the SELL/close
row from the dashboard table. Skip canceled TP/SL rows except to
note their existence — **canceled orders do NOT count as fills**.

| Field | Where to find it in the dashboard | Notes |
| --- | --- | --- |
| open_order_id | "Order ID" column for the buy_to_open row | UUID-shaped |
| close_order_id | "Order ID" column for the sell_to_close row | UUID-shaped |
| open_order_type | "Type" column for the buy row | limit / market |
| close_order_type | "Type" column for the sell row | limit / market |
| open_qty | "Qty" column for the buy row | integer |
| close_qty | "Qty" column for the sell row | integer |
| open_filled_qty | "Filled qty" or "Qty filled" for the buy | integer |
| close_filled_qty | same for the sell | integer |
| open_avg_fill_price | "Avg fill price" or "Filled at" price for the buy | float |
| close_avg_fill_price | same for the sell | float |
| open_total_amount | "Total amount" or "Notional" for the buy | float |
| close_total_amount | same for the sell | float |
| open_submitted_at | "Submitted at" timestamp for the buy | ISO-8601 |
| open_filled_at | "Filled at" timestamp for the buy | ISO-8601 |
| close_submitted_at | "Submitted at" timestamp for the sell | ISO-8601 |
| close_filled_at | "Filled at" timestamp for the sell | ISO-8601 |
| source | "Source" column if present (e.g. `access_key`, `web`, `mobile`) | label |
| submitter_source | same as `source` — relevant for audit-gap diagnosis | label |
| canceled_tp_order_id | If a TP child sell at limit was canceled, its order_id | UUID or null |
| canceled_sl_order_id | If an SL child sell at stop was canceled, its order_id | UUID or null |
| canceled_tp_price | The TP limit price the child carried (e.g. $558.33) | float or null |
| canceled_sl_price | The SL stop price the child carried (e.g. $473.58) | float or null |

## What to do with the values

Open `learning-loop/position_reconciliation/manual_order_history_remaining_2026-06-04.json`
and fill in the corresponding fields per symbol. Then change the
symbol's `data_quality` field from `REQUIRES_OPERATOR_EXTRACTION` to:

- **`COMPLETE`** — both BUY + SELL prices and qty are present.
- **`PARTIAL`** — some fields filled, some missing.
- **`MISSING_CLOSE_PRICE`** — BUY done, SELL price not yet provided.
- **`MISSING_OPEN_PRICE`** — rare, SELL done, BUY price not yet provided.

The reconstruction helper `shared/trade_reconstruction.py::trade_from_manual_order_history`
will then build a `TRADE_CLOSED_WITH_PNL_MANUAL_ORDER_HISTORY` entry
with the real realized P/L. If either price is missing, it will return
`TRADE_CLOSED_PRICE_MISSING` and **no fake P/L will be invented**.

## What this checklist is NOT

- **NOT** asking the operator to provide API keys, app passwords, or
  any credential. Only sanitized table values from the dashboard.
- **NOT** asking the operator to enable broker_paper or live trading.
- **NOT** asking the operator to close, modify, or cancel any open
  positions.
- **NOT** asking for screenshots or any UI export. Just the table
  values.

## Why this matters

Without these prices the analyzer cannot attribute the remaining
~$5,304 of the drawdown to specific symbols. Strategies that opened
and closed within hours on 2026-06-04 are currently marked as
`SILENT 64 days` because `learning-loop/analyzer.py::reconstruct_trades`
couldn't FIFO-pair their opens with their closes (see v3.23
`shared/trade_reconstruction.py` for the deterministic repair).
Filling in this data closes the reconciliation gap and unblocks the
LLM Senior PM persona's view of strategy performance.

## Safety reminders

- `EDGE_GATE_ENABLED` stays `false`.
- `ALLOW_BROKER_PAPER` stays unset.
- Live trading stays blocked.
- Drawdown guard at -3.0% stays active.
- Equity baseline (`state.json::cumulative.starting_equity`) stays
  static until the operator explicitly resets it (operator-level
  decision, **not** automated).
