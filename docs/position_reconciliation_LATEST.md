# Alpaca Paper Position Reconciliation Report

**Generated:** 2026-06-08 (v3.23.1 — refined AMD after operator pulled Order History)
**Status:** `DASHBOARD_VERIFIED_POSITIONS_CONFLICT_WITH_LOCAL_INFERENCE`
**Previous report status:** `STALE_INFERRED_POSITIONS_NOT_DASHBOARD_VERIFIED`

## v3.23.1 update — AMD now reconciled

After v3.23 shipped the broker-state reconciliation modules,
operator pulled the actual Alpaca paper Order History for AMD and
provided sanitized values. AMD is no longer in the
`BROKER_SIDE_CLOSED_OR_DASHBOARD_VERIFIED_NOT_OPEN` bucket — it's
now in the more precise `EXTERNAL_API_MARKET_CLOSE_VERIFIED_FROM_DASHBOARD`
status, with secondary audit-gap finding
`MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT`.

### AMD trade pair (from sanitized manual Order History)

| Side | Type | Qty | Avg fill | Total $ | Filled at | Submitter |
| --- | --- | --- | --- | --- | --- | --- |
| buy_to_open | limit | 34 | $497.875 | $16,927.75 | 2026-06-05T15:39:57-04:00 | access_key |
| sell_to_close | **market** | 34 | $485.02 | $16,490.68 | 2026-06-05T17:35:45-04:00 | **access_key** |

Plus 2 canceled protective orders (do NOT count as fills):

- Limit sell_to_close @ $558.33 canceled 2026-06-05T16:00:48-04:00
- Stop sell_to_close @ $473.58 canceled 2026-06-05T16:00:43-04:00

### AMD realized P/L

| Field | Value |
| --- | --- |
| Buy total | $16,927.75 |
| Sell total | $16,490.68 |
| Realized P/L | **-$437.07** |
| P/L % | **-2.58%** |

### Audit gap finding

The close was a market sell submitted via Alpaca `access_key` but
NO matching `safe_close` event exists in
`journal/autonomy/2026-06-04.jsonl` or `2026-06-05.jsonl`. This is
the v3.23.1 finding `MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT`.
Some external script/manual workflow/one-shot bypassed
`shared/alpaca_orders.py::safe_close()`. Required action:
**`INVESTIGATE_MARKET_CLOSE_WITHOUT_SAFE_CLOSE_AUDIT`**.

### Impact on drawdown

- AMD's -$437 explains **only ~7.6% of the -$5,741 baseline drop**.
- Remaining ~-$5,304 likely from the CRWD/NOW/QQQ/SPY/GLD/PANW/ORCL
  `safe_close` cycle at 06-04 14:00-14:20 UTC, but exact fill prices
  are still pending operator extraction from the dashboard.

### Older AMD trades (May 27/28/29, Jun 03)

Operator also provided older AMD rows. **They are intentionally
NOT used in this incident reconstruction** because (a) they
belong to different open/close cycles outside the 2026-06-04
allocator-batch window, and (b) the system has no matching local
open/close events for them in the incident window. They are
documented in
`learning-loop/position_reconciliation/manual_order_history_AMD_2026-06-04.json`
under `ignored_trade_pairs` for audit completeness.

---


## TL;DR — what's actually open vs what local state thinks

**Operator verified via Alpaca paper dashboard "View All positions":**

| Position | Market value | Unrealized P/L | Dashboard? | Local position-manager state |
| --- | --- | --- | --- | --- |
| ETHUSD | ~$8,514 | **+$523** | YES | TIME_EXPIRED (exit-monitor trying to close, blocked by bracket interlock) |
| AVAXUSD | ~$2,451 | -$45 | YES | CLOSED (stale!) |
| SOLUSD | dust | dust | YES | CLOSED (stale!) |
| LTCUSD | dust | dust | YES | CLOSED (stale!) |
| **Total open** | **~$10,965** | **~+$478** | — | — |

**8 equity positions inferred in previous report are NOT open:**
- AMD, CRWD, PANW, ORCL, NOW, SPY, QQQ, GLD — **NOT on dashboard**.

## Why the previous inference was wrong

The previous report inferred the 8 equity positions from
`learning-loop/allocations/2026-06-04.execution.json` (which showed
8 BUYs all `status=placed` at 13:45 UTC). It missed that within hours
of opening, the exit-monitor closed 7 of them via `safe_close` events
on the same day:

```
journal/autonomy/2026-06-04.jsonl:
  14:00:33  safe_close(GLD, 16)   FAILED  (bracket holding qty)
  14:05:26  safe_close(QQQ, 13)   PLACED
  14:20:28  safe_close(CRWD, 19)  PLACED
  14:20:28  safe_close(NOW, 107)  PLACED
  ... and more
```

7 of 8 symbols have at least 1 `safe_close` event on 06-04. Only AMD
has zero close events — see §5 for the AMD anomaly.

## 1. Credentials status

| Check | Value |
| --- | --- |
| Credentials present in local env | NO (`ALPACA_API_KEY` / `ALPACA_SECRET_KEY` both MISSING) |
| Operator-provided dashboard data | YES (manual verification by operator at session start) |
| Paper endpoint verified | YES |
| Live endpoint blocked | YES |
| Status code | `ALPACA_API_UNAVAILABLE_BUT_OPERATOR_DASHBOARD_VERIFIED_POSITIONS_PROVIDED` |

## 2. Account summary (local equity history; dashboard not queried)

| Field | Value |
| --- | --- |
| Equity (2026-06-08) | $90,119.76 |
| Baseline (`state.json::cumulative.starting_equity`) | **$93,700.09** (STATIC since reset) |
| Peak (`state.json::peak_equity`) | $98,446.36 |
| Cumulative ROI vs starting baseline | **-3.82%** |
| Cumulative ROI vs peak | -8.46% |
| Inferred cash ≈ equity − portfolio | ~$79,155 ($90,120 − $10,965) |
| `state.json::cumulative.total_trades` | **0** (wiring bug — see §6) |

## 3. Dashboard-verified open positions (operator)

| Symbol | Market value | Unrealized P/L | Notes |
| --- | --- | --- | --- |
| ETHUSD | ~$8,514 | **+$523** | Exit-monitor failing to close (bracket interlock at 03:50-10:55 UTC); position is in time-stop window |
| AVAXUSD | ~$2,451 | -$45 | New position opened recently (local state stale) |
| SOLUSD | dust | dust | Dust qty after partial close (local state says CLOSED) |
| LTCUSD | dust | dust | Dust qty after partial close (local state says CLOSED) |

## 4. Equity positions previously inferred — REJECTED

The 8 BUYs from 2026-06-04 are **NOT currently open** per dashboard:

| Symbol | Inferred cost basis | Inferred state | Audit shows close event? | Actual state |
| --- | --- | --- | --- | --- |
| AMD | $16,949.34 | ARMED (still open) | **NO** | NOT on dashboard — see §5 ANOMALY |
| CRWD | $13,119.50 | unknown | YES (06-04 14:20) | CLOSED |
| ORCL | $13,083.06 | unknown | YES | CLOSED |
| PANW | $13,135.20 | unknown | YES | CLOSED |
| NOW | $13,065.77 | unknown | YES (06-04 14:20) | CLOSED |
| SPY | $9,020.64 | unknown | YES | CLOSED |
| QQQ | $9,538.49 | unknown | YES (06-04 14:05) | CLOSED |
| GLD | $6,625.60 | unknown | partial (06-04 14:00 FAILED then PLACED) | CLOSED |

All previously labeled `STALE_INFERRED_POSITIONS_NOT_DASHBOARD_VERIFIED`.

## 5. AMD anomaly

- `runtime_state.json::positions.AMD.lifecycle = ARMED` → local position-manager believes AMD is still open
- `journal/autonomy/2026-06-04.jsonl` shows ZERO `safe_close` events for AMD
- Operator's dashboard verification shows AMD is **NOT open**

Possible explanations (need API to confirm):

1. AMD was closed by a bracket-child SL/TP that fired without going through `safe_close` (i.e. Alpaca server-side OCO trigger) — most likely, and would not appear in the audit JSONL.
2. AMD was closed silently in a different runner that didn't write to audit.
3. `runtime_state.json::positions.AMD` is stale and was never updated when the bracket child fired.

The most likely answer is **(1) + (3)**: an SL/TP child filled at the broker, the position closed at Alpaca, but `position-manager` never reconciled because no monitor told it. This is a known wiring gap (position lifecycle state needs broker-side reconciliation).

## 6. Drawdown source diagnosis

| Question | Answer |
| --- | --- |
| Does dashboard explain the -$5,741 drawdown? | **NO.** Open positions sum to ~$10,965 with +$478 unrealized. They cannot account for the -$5,741 drop. |
| Where does the loss come from? | **Realized losses** on the 7 equity positions that opened + closed on 2026-06-04 within hours. The audit JSONL shows the close events but the analyzer's `compute_today_stats` was unable to FIFO-pair them. |
| Why is `cumulative_trades = 0` in `state.json`? | **WIRING BUG in `learning-loop/analyzer.py::reconstruct_trades`** — the close events exist in audit JSONL but the analyzer cannot match them to their opens (different naming conventions between `allocator-rebalance` orders and `safe_close` orders, OR the analyzer reads only one source while closes live in another). |
| Is the baseline ($93,700) stale? | LIKELY — `state.json::cumulative.starting_equity = 93700.08782721018` is static. It hasn't been updated since reset. Peak is $98,446 (correctly tracked) but starting is frozen. |
| Is the drawdown -3.82% real? | YES — equity actually dropped from baseline. The MECHANISM (realized vs unrealized) was misdiagnosed in the previous report. |
| Should drawdown guard be disabled? | **NO.** The drawdown is real; the guard is correctly halting new entries. |

## 7. Safety findings (updated)

- **Orphan positions: ETHUSD** — local position-manager has it as `TIME_EXPIRED`, exit-monitor tries to close it every 5 min and Alpaca returns 403 "insufficient balance for ETH (requested: 5.072 ≤ balance: 5.0724058)". This looks like a precision rounding error at Alpaca, NOT a real bracket interlock. Operator manual review recommended.
- **Position-manager state widely stale** — AVAXUSD/SOLUSD/LTCUSD all show `CLOSED` in `runtime_state.json::positions` but are open on dashboard. This is a known reconciliation gap.
- **Analyzer trade attribution broken** — `cumulative_trades = 0` despite confirmed close events in audit JSONL. The closes are happening but not visible to the LLM Senior PM persona, which is why crypto-momentum / geo-* strategies look SILENT for 64 days even though they're actually executing.
- **AMD position lifecycle gap** — see §5.
- **Missing API call** for definitive reconciliation.

## 8. Recommendation

**`INVESTIGATE_EQUITY_BASELINE_AND_ACCOUNT_HISTORY`** + **`KEEP_DRAWDOWN_GUARD_ACTIVE`**

Reasoning:
- The drawdown is real (-3.82%) — guard is correctly halting new entries.
- The previous report's local inference of 8 open equity positions was wrong; operator manual dashboard verification is the source of truth.
- The dashboard-visible positions (ETHUSD +$523, AVAXUSD -$45, SOL/LTC dust) cannot explain -$5,741 drop → drawdown comes from realized losses on the 8 rapid-close positions on 2026-06-04.
- ETHUSD does NOT need manual close — it's at +$523 (peak +$764 / trough -$326), exit-monitor will eventually flatten it once Alpaca precision settles.
- AVAXUSD does NOT need manual close — small position with small loss.

## 9. What operator should do next

1. **Sprawdzić Alpaca paper dashboard → Account activity / Order history** dla 2026-06-04 14:00-15:00 UTC — potwierdzić, że 7 equity positions zostały zamknięte (CRWD/NOW/QQQ/SPY/GLD/PANW/ORCL).
2. **Sprawdzić AMD trade history** — czy SL/TP bracket child filled?
3. **DO NOT close ETHUSD manually** — pozycja jest na plusie (+$523), exit-monitor obsługuje.
4. **DO NOT close AVAXUSD manually** — mała strata, w normie.
5. **DO NOT lower drawdown_guard threshold** — guard działa poprawnie.
6. **DO NOT enable ALLOW_BROKER_PAPER=true** — niepotrzebne.
7. **DO NOT flip EDGE_GATE_ENABLED=true**.
8. Operator może rozważyć: czy state.json::cumulative.starting_equity ($93,700) powinien zostać zresetowany do bieżącej equity (aby drawdown był liczony od nowego baseline), ale to operator-level decision wymagająca review.

## 10. Final answers to spec questions

| Question | Answer |
| --- | --- |
| Czy dashboard potwierdza 8 equity positions? | **NIE** |
| Czy obecne dashboard-visible positions tłumaczą drawdown? | **NIE** (~$10,965 portfolio + ~+$478 unrealized cannot explain -$5,741 loss) |
| Czy ETH/AVAX wymagają manual close? | **NIE** na podstawie obecnych danych |
| Czy drawdown guard powinien być wyłączony? | **NIE** — guard działa poprawnie |
| Co dalej? | **`INVESTIGATE_EQUITY_BASELINE_AND_ACCOUNT_HISTORY`** + sprawdzić Alpaca order history za 06-04 |

## 11. Invariants verified

- `live_trading_disabled`: **True**
- `edge_gate_enabled`: **False**
- `allow_broker_paper`: **False** (unset)
- `read_only`: **True**
- `does_not_close_positions`: **True**
- `does_not_place_orders`: **True**
- `does_not_modify_runtime_state`: **True** (this report does not patch `state.json` or `runtime_state.json`)

This update was generated WITHOUT any Alpaca API call. No orders placed. No positions modified. No live URL hit. No `runtime_state.json` or `state.json` mutation.
