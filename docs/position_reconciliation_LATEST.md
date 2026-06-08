# Alpaca Paper Position Reconciliation Report

**Generated:** 2026-06-08 (read-only diagnostic; no orders placed; no positions modified)
**Status:** `POSITION_RECONCILIATION_UNAVAILABLE_NO_CREDENTIALS` (Alpaca paper API not reachable from this local session) → falls back to **local-state-only reconciliation**.

## 1. Credentials status

| Check | Value |
| --- | --- |
| Credentials present in local env | **NO** (`ALPACA_API_KEY` / `ALPACA_SECRET_KEY` both MISSING in shell) |
| Paper endpoint verified | YES — `https://paper-api.alpaca.markets` is the only endpoint referenced in `shared/autonomy.py::PAPER_BASE_URL`, `shared/risk_guards.py`, `shared/alpaca_orders.py`, `scripts/position_reconciliation_report.py:77` |
| Live endpoint blocked | YES — `shared/autonomy.py::assert_paper_only()` defined at line 100; AST lint gate `test_no_naked_sell_v3910.py` enforced in CI |
| Reconciliation script available | YES — `scripts/position_reconciliation_report.py` (fail-soft when creds missing) |

## 2. Account summary (from local equity history — NOT live Alpaca call)

| Field | Value |
| --- | --- |
| Equity (2026-06-08) | **$90,119.76** |
| Equity (2026-06-04 close) | $95,861.26 |
| Baseline (2026-06-04 open) | $93,700.09 |
| Cumulative drop 06-04→06-08 | **-$5,741** (~-5.99% of cost basis) |
| Cumulative ROI vs baseline | **-3.82%** |
| Cash | unknown without API call |
| Buying power | unknown without API call |
| Portfolio value | unknown without API call |
| Total unrealized P&L | inferred ~ **-$5,741** (matches the equity drop assuming no closed trades) |

## 3. Open positions (inferred from 2026-06-04 allocator execution.json)

These are the 8 BUY orders placed successfully by the allocator on 2026-06-04 13:45 UTC. All `status=placed` (no failure or skip). They explain the cumulative drawdown.

| Symbol | Qty | Cost basis | Entry @ | Current value | Inferred unrealized | Has exit/stop | Local audit link |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AMD | 34 | $16,949.34 | $498.51 | unknown | unknown | unknown (need API) | `learning-loop/allocations/2026-06-04.execution.json` |
| CRWD | 19 | $13,119.50 | $690.50 | unknown | unknown | unknown (need API) | same |
| ORCL | 58 | $13,083.06 | $225.57 | unknown | unknown | unknown (need API) | same |
| PANW | 48 | $13,135.20 | $273.65 | unknown | unknown | unknown (need API) | same |
| NOW | 107 | $13,065.77 | $122.11 | unknown | unknown | unknown (need API) | same |
| SPY | 12 | $9,020.64 | $751.72 | unknown | unknown | unknown (need API) | same |
| QQQ | 13 | $9,538.49 | $733.73 | unknown | unknown | unknown (need API) | same |
| GLD | 16 | $6,625.60 | $414.10 | unknown | unknown | unknown (need API) | same |
| **TOTAL** | — | **$94,537.60** | — | — | **~-$5,741** | — | — |

Note: 2026-06-05's allocator execution.json shows 8 BUYs all **failed** with the (now-deprecated) bare `"Alpaca rejected order (see stdout)"` reason — likely BP exhaustion from the 8 successful positions above. v3.22.0 added structured rejection categorization to prevent this opacity in future.

## 4. Open orders

Cannot enumerate without API call. The allocator's exit/stop bracket children typically auto-place after each BUY (`place_stock_bracket` writes them as GTC since v3.9.6).

| Symbol | Side | Type | Status | Qty | Limit/stop | Created at | Linked position |
| --- | --- | --- | --- | --- | --- | --- | --- |
| — | — | — | — | — | — | — | — |

## 5. Drawdown attribution

- **Largest losing positions (by cost basis size):** AMD ($16.9k), CRWD ($13.1k), PANW ($13.1k), ORCL ($13.1k), NOW ($13.1k). These 5 alone are $69k+ of cost basis (~73% of total exposure).
- **Positions from 2026-06-04 still open:** ALL 8 inferred to be open. No closing trades attributed in `learning-loop/history/2026-06-08.md` (`Cumulative trades: 0`).
- **Does Alpaca match local equity gap?** Inferred YES — the -$5,741 drop matches the equity-gap WARN flagged daily by `analyzer.py::compute_equity_gap_alert`. Need API call to confirm position-level numbers.
- **Does drawdown guard correctly halt new entries?** **YES.** -3.82% > -3.0% threshold → `daily_drawdown_guard` returns HALT. Confirmed live via `learning-loop/opportunity_ledger/2026-06-08.jsonl` (86 entries today, all `HALTED_BY_DRAWDOWN_GUARD`).

## 6. Safety findings

- **Orphan positions:** none can be definitively flagged without API call, but all 8 inferred positions have audit links to `2026-06-04.execution.json`.
- **Missing stop-loss:** cannot verify without API call. `shared/alpaca_orders.py::place_stock_bracket` writes SL+TP children as GTC by default since v3.9.6, so 2026-06-04 positions SHOULD have them. Operator manual check recommended.
- **Missing exit plan:** v3.17.0+ writes `runtime_state.json::positions` with `INTAKE/ARMED/TRAILING` lifecycle tags. Check whether the 8 positions appear there.
- **Audit gaps:** none in execution.json attribution.
- **Buying power issues:** highly likely. 2026-06-05 allocator's 8 BUYs ALL rejected — diagnosed as BP exhaustion from the 06-04 positions. v3.22.0 + v3.22.3 BP guard now pre-checks this before each batch.
- **Action required:** **operator must log into Alpaca paper dashboard** to verify the 8 positions are still open + have SL/TP children.

## 7. Recommendation

**`REVIEW_OPEN_POSITIONS_MANUALLY`** + **`KEEP_DRAWDOWN_GUARD_ACTIVE`**

Reasoning:
- The drawdown guard is correctly doing its job (blocking new entries while paper account is down -3.82%).
- The 8 positions opened on 2026-06-04 are the most likely source of the unrealized loss.
- Operator must verify in Alpaca paper dashboard:
  1. Which of the 8 positions are still open?
  2. Do they all have GTC bracket SL/TP children (per v3.9.6)?
  3. What is the per-position unrealized %?
  4. Is any single position responsible for >30% of the drawdown?
- DO NOT close positions automatically. DO NOT enable `ALLOW_BROKER_PAPER=true`. DO NOT flip `EDGE_GATE_ENABLED=true`. DO NOT lower the drawdown guard threshold.

## 8. Next steps (operator-side)

```bash
# After exporting ALPACA_API_KEY + ALPACA_SECRET_KEY for the paper account:
ALPACA_API_KEY=... ALPACA_SECRET_KEY=... \
    python3 scripts/position_reconciliation_report.py

# Will re-render this document with live position-level numbers.
```

Or operator may inspect manually at the Alpaca paper dashboard
(per CLAUDE.md Environment & Accounts section, account `PA3KNZV29BP5`).

## 9. Invariants verified (from `scripts/position_reconciliation_report.py`)

- `live_trading_disabled`: **True**
- `edge_gate_enabled`: **False**
- `read_only`: **True**
- `does_not_close_positions`: **True**
- `does_not_place_orders`: **True**

This report was generated WITHOUT any Alpaca API call from this
session. No orders placed. No positions modified. No live URL hit.
