# Trade Reconstruction (v3.23)

`shared/trade_reconstruction.py` repairs the FIFO pairing that
`learning-loop/analyzer.py::reconstruct_trades` couldn't handle when
opens and closes flow through different naming conventions
(`allocator-rebalance` vs `safe_close`).

## Why this exists

On 2026-06-08 we observed:

```
state.json::cumulative.total_trades = 0
```

despite `journal/autonomy/2026-06-04.jsonl` containing 7 `safe_close`
events paired with 8 `allocator-rebalance` BUYs from
`learning-loop/allocations/2026-06-04.execution.json`. The analyzer
couldn't match them, so the LLM Senior PM persona saw every strategy
as SILENT 64 days even though they were actively trading.

## What it returns

`TradeReconstructionReport` with:

- `trades` — paired (open, close) lots with status:
  - `TRADE_CLOSED_WITH_PNL` (both prices present)
  - `TRADE_CLOSED_PRICE_MISSING` (one or both missing — no fake P&L)
  - `TRADE_PARTIAL_CLOSE` (only part of the lot was consumed)
- `unmatched_opens` — lots with no matching close (still open OR
  reconstruction bug)
- `unmatched_closes` — closes with no matching open (orphan close)
- `broker_side_close_inferred` — opens where dashboard says NOT_open
  but no `safe_close` exists in audit. Likely bracket SL/TP fired at
  broker. Requires Alpaca order history for close price. Status:
  `TRADE_BROKER_SIDE_CLOSE_INFERRED`.
- `metrics` — per-bucket counts so downstream code can detect a
  reconstruction failure (any `unmatched_*` > 0).

## Invariants

- `NEVER_PLACES_ORDERS = True`
- `NEVER_INVENTS_PRICES = True`
- `NEVER_MARKS_OPEN_AS_CLOSED_WITHOUT_EVIDENCE = True`

The module never auto-disables a strategy. Callers (silent strategy
classifier) explicitly block auto-disable when reconstruction is
incomplete.

## What this does NOT do

- Does NOT place orders.
- Does NOT close positions.
- Does NOT modify `state.json` or `runtime_state.json`.
- Does NOT touch `EDGE_GATE_ENABLED` or `ALLOW_BROKER_PAPER`.
- Does NOT invent P&L when fill prices are missing.

## Tests

`tests/test_trade_reconstruction_v3230.py` covers:

- BUY + safe_close pair → closed trade with realized P&L
- AMD anomaly: BUY + dashboard NOT_open + no safe_close →
  `TRADE_BROKER_SIDE_CLOSE_INFERRED`
- partial close (FIFO)
- unmatched close stays orphan
- unmatched open stays open without invented close
- close_price missing → `TRADE_CLOSED_PRICE_MISSING` (no fake P&L)
- 2026-06-04 scenario: 7 paired + 1 inferred = 8 reconstructed
  trades (cumulative MUST NOT be 0)

---

## v3.23.2 addendum — 7-symbol placeholder reconstruction (2026-06-08)

The 7 equity positions opened by allocator-rebalance on 2026-06-04
(CRWD / NOW / QQQ / SPY / GLD / PANW / ORCL) are still pending
operator extraction. v3.23.2 adds:

- `learning-loop/position_reconciliation/manual_order_history_remaining_2026-06-04.json`
  — placeholder JSON with `data_quality=REQUIRES_OPERATOR_EXTRACTION`
  per symbol and every `open_avg_fill_price` / `close_avg_fill_price`
  set to `null`. Reconstruction explicitly stays blocked until
  operator transcribes Order History values; the helper
  `trade_from_manual_order_history()` returns
  `TRADE_CLOSED_PRICE_MISSING` when invoked with `None` price, so
  invented P&L cannot leak through.
- `docs/OPERATOR_ORDER_HISTORY_EXTRACTION_CHECKLIST.md` documents
  exactly which fields the operator must transcribe per symbol from
  the dashboard's Order History view. No credentials are requested.
- `shared/drawdown_attribution.py` adds four new statuses
  (`DRAWDOWN_ATTRIBUTION_COMPLETE` / `PARTIAL` /
  `REQUIRES_ORDER_HISTORY` / `CONFLICT`) plus a
  `compute_partial_attribution()` helper. Current state is
  `PARTIAL`: AMD's -$437.07 is known, the 7 remaining symbols are
  unknown, residual ~-$5,304 is pending operator extraction.
- `tests/test_remaining_trade_reconstruction_v3232.py` enforces:
  placeholder file is valid JSON with 7 entries; all
  `data_quality=REQUIRES_OPERATOR_EXTRACTION`; checklist contains
  every symbol AND disclaims credential collection; canceled TP/SL
  orders never enter the P&L computation.


---

## v3.24.0 addendum — full order-history reattribution (2026-06-08)

Operator provided the broader Alpaca paper Order History export. The
7 placeholder symbols in
`learning-loop/position_reconciliation/manual_order_history_remaining_2026-06-04.json`
are now fully reconstructed:

| Symbol | Open qty @ price | Close qty @ price | Realized P/L |
|---|---|---|---:|
| CRWD | 19 @ 685.598421 | 19 @ 678.41 | -$136.58 |
| NOW | 107 @ 121.966168 | 107 @ 121.682243 | -$30.38 |
| QQQ | 13 @ 733.676923 | 13 @ 733.142308 | -$6.95 |
| SPY | 12 @ 751.68 | 12 @ 753.245 | +$18.78 |
| GLD | 16 @ 414.091875 | 16 @ 412.515625 | -$25.22 |
| PANW | 48 @ 273.19 | 48 @ 272.126667 | -$51.04 |
| ORCL | 58 @ 225.323104 | 58 @ 232.766552 | +$431.72 |
| **7 non-AMD subtotal** | | | **+$200.33** |
| AMD | 34 @ 497.875 | 34 @ 485.02 | -$437.07 |
| **Full 8-symbol equity batch** | | | **-$236.74** |

All entries flipped from `data_quality=REQUIRES_OPERATOR_EXTRACTION`
to `data_quality=COMPLETE_FROM_OPERATOR_EXPORT`. No prices were
invented; helper `trade_from_manual_order_history()` was not needed
because operator-supplied avg-fill values are authoritative.

**Old hypothesis obsolete:** the v3.23.1 / v3.23.2 placeholder note
that the remaining 7 equity trades would explain ~-$5,304 of the
drawdown is now **disproved**. The full 8-symbol equity batch is
close to flat (-$236.74). Drawdown reattribution lives in
`learning-loop/position_reconciliation/latest.json::v324_followups`
and in `docs/INCIDENT_2026_06_07.md`.
