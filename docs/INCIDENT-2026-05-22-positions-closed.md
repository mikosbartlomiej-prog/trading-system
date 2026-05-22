# Incident report — 7 positions auto-closed by RECREATE_EXIT_PLAN

**Date:** 2026-05-22
**Severity:** P1 — design bug, not data loss; ended in profit by luck
**Outcome:** +$1,404.97 realized profit (+1.46% intraday); all 7 positions liquidated
**Status:** Root-caused; fix needed before next position cycle

## TL;DR

`autonomous-remediation` workflow correctly detected "positions have no
exit order" after bracket OCO children expired at session end (DAY TIF).
But its `RECREATE_EXIT_PLAN` action — documented as "places fresh SELL
LIMIT for unprotected pos" — actually delegates to `execute_emergency_close`
which issues **MARKET SELL** orders, prematurely closing positions instead
of restoring SL/TP protection.

Implementation/documentation mismatch in `shared/remediation.py`.

## Timeline (UTC)

| Time | Event |
|---|---|
| **2026-05-21 14:11–14:26** | Morning allocator placed 7 BUY brackets (AMD/CRWD/GLD/NOW/PANW/QQQ/SPY) with OCO SL+TP children (DAY TIF default) |
| 2026-05-21 ~14:30 | All 7 positions filled |
| **2026-05-21 ~20:00** | Market close. Alpaca **DAY-TIF bracket children EXPIRED + paired SL canceled** — positions now "naked" (no exit order attached) |
| **2026-05-21 20:12:19** | `autonomous-remediation` cron fired |
| 2026-05-21 20:12:19–43 | Health check: `positions_have_exit.missing = [AMD, CRWD, GLD, NOW, PANW, QQQ, SPY]`. Remediation enqueues 7× `RECREATE_EXIT_PLAN` actions |
| 2026-05-21 20:12:38–43 | `_do_recreate_exit_plan(sym)` → `execute_emergency_close(EmergencyTarget(suggested_action="CANCEL_AND_DELETE"))` → **MARKET SELL** orders submitted to Alpaca for all 7 symbols |
| 2026-05-21 20:12+ | Alpaca rejects/cancels MARKET orders outside market hours (paper API behavior) |
| 2026-05-21 21:48 / 22:11 / 23:32 / 02:15 / 06:29 / 09:56 UTC | Subsequent remediation crons re-detect "no exit order" each tick (cooldown 1h means re-fire every 1h). Each places fresh SELL orders. Some queue successfully for next session. |
| **2026-05-22 13:30:13–13:33:45** | Market opens. **Queued SELL MARKETs fill immediately** — 7 positions closed at market prices, total realized profit +$1,404.97 |
| 2026-05-22 13:57:46 | Exit-monitor sees 0 positions, equity $97,832.94 |
| 2026-05-22 14:34 | Operator notices "all positions closed", asks if by design |

## Root cause analysis

### 1. Bracket DAY TIF causes overnight unprotection

Alpaca's bracket order semantics:
- Parent BUY + OCO children (SL + TP) all share TIF
- Default in `shared/alpaca_orders.py::place_stock_bracket` is `time_in_force: "day"`
- DAY children **expire at market close**, then paired sibling is canceled (OCO)
- Position remains open overnight with NO active exit orders

This creates a daily "naked overnight" window for every multi-day position.

### 2. `RECREATE_EXIT_PLAN` actually market-closes the position

`shared/remediation.py::_do_recreate_exit_plan(action)`:

```python
def _do_recreate_exit_plan(action: RemediationAction) -> dict:
    """
    Recreating an exit plan from scratch needs current quote + entry. Rather
    than reimplement the per-strategy exit logic, we delegate to
    emergency_engine: a position with no exit plan is by definition an
    emergency-close target (the engine produces the right kind of close).
    """
    target = EmergencyTarget(
        symbol=sym, reason=action.reason,
        suggested_action="CANCEL_AND_DELETE",
    )
    return execute_emergency_close(target, actor="remediation")
```

Documentation says "places fresh SELL LIMIT for unprotected pos" but
implementation issues a MARKET SELL via emergency_engine. The two are
fundamentally different operations:
- **Intent** (per docstring): restore protection — keep position alive
  with new TP/SL orders
- **Actual** (per code): emergency close — sell at market immediately

### 3. Cooldown set to 1h but executions stacked

`shared/remediation.py` enforces per-(action,symbol) cooldown of 1h.
After 20:12 UTC the first batch of MARKET SELLs got canceled because
market was closed. Cooldown then prevented re-fire until 21:12 UTC.
But the 21:48 remediation run was past cooldown → re-fired SELL MARKETs.
And so on overnight, until one set queued correctly for market open.

## What worked correctly

- ✅ Health check correctly identified missing exit orders
- ✅ Audit log captured FSM state changes (GIVEBACK_WARN transition)
- ✅ Emergency close mechanism actually executed the trades cleanly
- ✅ Profit was preserved (positions had appreciated overnight; closing
  at market open captured gains)

## What's broken

- ❌ Bracket OCO uses DAY TIF — children expire every session end,
  creating daily unprotection windows
- ❌ `RECREATE_EXIT_PLAN` doesn't recreate anything — it market-closes
- ❌ This means EVERY multi-day position will be auto-liquidated the
  morning after entry, regardless of strategy intent
- ❌ Strategy TP/SL targets are ignored (planned +12% TP / -5% SL never
  had a chance to fire — positions sold at random market prices instead)
- ❌ This is a **time bomb**: today we got lucky (positions in profit
  at market open); next time positions in loss → unnecessary realized losses

## Why it ended in profit today

The 7 positions placed yesterday had appreciated overnight (~+0% to +4%
per exit-monitor at 11:48 UTC). When MARKET SELLs queued by overnight
remediation cycles fired at 13:30 UTC market open, prices were even
higher (market typically opens with momentum). Total realized: +$1,405.

Pure luck — not by design. Same mechanism with a -2% overnight gap
would have realized -$2k losses instead.

## Fix recommendations (P1 — implement before next position cycle)

### Option A — Make RECREATE_EXIT_PLAN actually recreate (preferred)

`shared/remediation.py::_do_recreate_exit_plan` should:
1. Query current position (symbol, qty, avg_entry_price)
2. Compute fresh SL/TP based on strategy defaults
3. Submit LIMIT SELL @ TP + STOP SELL @ SL (separate orders, GTC TIF)
4. Return success only after both submitted

This matches the docstring intent + preserves strategy planning.

### Option B — Use GTC TIF for bracket OCO children

`shared/alpaca_orders.py::place_stock_bracket` change
`time_in_force="day"` → `time_in_force="gtc"` for the bracket parent.

Pros: simpler. OCO children survive across sessions.
Cons: requires verifying Alpaca paper supports GTC brackets (some
brokers reject GTC OCO).

### Option C (interim) — Disable RECREATE_EXIT_PLAN entirely

Add env flag `REMEDIATION_DISABLE_RECREATE=true` to skip this action.
Positions stay naked overnight but at least don't get force-closed.
Operator manually reviews each morning.

**Recommended chain:**
1. **TODAY:** Option C (block RECREATE_EXIT_PLAN immediately)
2. **NEXT SESSION:** Option A (proper recreate logic with LIMIT + STOP GTC)
3. **AFTER FIX VERIFIED:** Optionally Option B for cleaner architecture

## Open backlog items added

- [P1] Fix `_do_recreate_exit_plan` to actually recreate exit orders
  (LIMIT @ TP + STOP @ SL, GTC), not market-close
- [P1] Add env flag `REMEDIATION_DISABLE_RECREATE` (interim safety
  net while fix in development)
- [P2] Audit other remediation actions for docstring vs implementation
  mismatch (full code review of `shared/remediation.py`)
- [P2] Verify bracket TIF behavior in `shared/alpaca_orders.py` —
  consider GTC default for bracket children

## Lessons learned

1. **Test through full position lifecycle** including overnight + next-day
   open. Today's incident wouldn't have surfaced in unit tests because
   tests don't simulate the bracket OCO expiration → remediation chain.

2. **Docstring drift is dangerous**. The `_do_recreate_exit_plan`
   docstring described intent ("places fresh SELL LIMIT") but
   implementation diverged ("emergency close via market sell"). This
   gap caused operator (Claude) to misunderstand system behavior when
   diagnosing.

3. **Profitable bugs are still bugs**. Today's outcome was good but the
   underlying mechanism is broken. Without the fix, the same pattern
   will eventually liquidate positions at unfavorable prices.

4. **Audit JSONL needs broader coverage**. Today's audit log only
   captured FSM transitions (governor), not the remediation actions.
   `_do_recreate_exit_plan` should emit an event so operators see
   "Remediation closed AMD at $477 — reason: no exit order" in JSONL.
