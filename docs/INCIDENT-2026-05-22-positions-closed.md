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

## Resolution (2026-05-22 EOD — v3.9.6 + 2026-05-23 — v3.9.7)

**All 4 P1 backlog items SHIPPED** in single commit `8f338dc` same day
(2026-05-22 EOD, ~30 min after incident closed). Plus follow-up fix
`2e2f505` (v3.9.7, 2026-05-23) for governor NEW_DAY peak preservation
bug that would have blocked Monday's open.

### v3.9.6 — Direct incident fix (commit `8f338dc`)

1. **GTC bracket TIF** (`shared/alpaca_orders.py::place_stock_bracket`)
   — `time_in_force: "day"` → `"gtc"`. Eliminates the original
   trigger condition (DAY-TIF expiration at market close).

2. **`place_oco_exit` helper** (`shared/alpaca_orders.py`, new)
   — paired LIMIT@TP + STOP@SL with GTC TIF + guards (qty/prices/side
   validation, TP/SL inversion check for long+short). Used by
   `_do_recreate_exit_plan` as the proper recovery mechanism.

3. **`_do_recreate_exit_plan` rewritten** (`shared/remediation.py`)
   — fetches position from Alpaca, computes TP/SL from
   `aggressive_profile.json::exits.stocks_etf` (+18%/-6%), submits
   OCO via `place_oco_exit`. **Position REMAINS OPEN.** Options +
   crypto correctly skipped (asset-class aware). client_order_id
   prefix `recreate-exit-` for audit attribution.

4. **`REMEDIATION_DISABLE_RECREATE` env flag** (operator kill-switch)
   — when `true`, skips RECREATE_EXIT_PLAN entirely. Default `false`.
   Set in `autonomous-remediation.yml` env.

5. **`autonomous-remediation.yml`** — `permissions: contents: read` →
   `write` + new "Commit audit journal" step with cherry-pick retry
   pattern (v3.9.4.4). Closes the forensic gap of 0 audit events for
   7+ position-affecting actions during this incident.

6. **Decision status SKIPPED** added to remediation audit emission
   (previously only EXECUTED/FAILED for skip paths). `RECREATE_EXIT_PLAN`
   now flagged `reversible=true` (rollback = cancel OCO + replace).

13 unit tests in `tests/test_recreate_exit_plan_v396.py`.

### v3.9.7 — Governor NEW_DAY follow-up fix (commit `2e2f505`)

Saturday morning audit discovered a separate bug exposed by the same
underlying mechanic:

**Symptom:** runtime_state.json showed `RED_DAY_AFTER_GREEN` at
2026-05-23 08:31 UTC with 0 positions, $0 actual intraday P&L, and
`intraday_peak_pnl: $1,404.97` (preserved from Friday). `max_gross_target`
clamped to 0.25 — would have blocked Monday's allocator BUY orders.

**Root cause:** `shared/intraday_governor.py::update()` on new_day
seeded `peak_pnl` from `max(prev_peak_pnl, daily_pl, 0.0)`. On
weekends/holidays, Alpaca's `last_equity` returns
previous-SESSION-OPEN (not previous-session-CLOSE), so daily_pl
computed yesterday's full P&L. Combined with NEW_DAY transition
preserving the alerts_sent dict, the governor effectively carried
yesterday's peak into today.

**Fix:** on new_day, hard-set `peak_pnl = 0` + `peak_equity = equity`
(baseline = current). Subsequent ticks accumulate naturally. Plus
manual reset of runtime_state.json to FLAT (commit included).

4 unit tests in `tests/test_governor_new_day_reset_v397.py` including
the 2026-05-23 incident replay scenario.

### Verification plan (Monday 2026-05-25)

See `docs/VERIFICATION-2026-05-25-monday.md` — 8-checkpoint plan to
verify v3.9.6 + v3.9.7 in production conditions:
- Sunday 04:00 UTC daily-learning generates plan
- Monday 01:30 UTC governor NEW_DAY transition with clean peak=0
- Monday 13:35 UTC morning-allocator opens 7 BUYs with GTC brackets
- Monday 20:00 UTC market close — brackets DO NOT expire
- 20:15+ UTC remediation — 0 actions taken (positions intact)
- Tuesday morning — positions still alive

Success criteria: positions stay alive Mon → Tue, no MARKET SELLs
by remediation.

Fallback path: if Alpaca paper rejects GTC bracket → v3.9.6
`_do_recreate_exit_plan` kicks in with proper OCO recreation (not
market close) → positions still protected, just via different
mechanism.

---

## REGRESSION 2026-05-26 — same incident class, different code path (v3.9.9)

**Date:** 2026-05-26 (Tuesday, first market day post-Memorial Day)
**Severity:** P0 — design bug, same class as 2026-05-22 but DIFFERENT path
**Outcome:** SPY/QQQ/GLD MARKET-closed (-$118 net) despite v3.9.6 ship; +$560 net daily by luck
**Status:** Resolved 2026-05-27 v3.9.9

### Why this happened despite v3.9.6

v3.9.6 fixed `_do_recreate_exit_plan` (the `no_exit_plan` handler). But
`shared/emergency_engine.py::scan_emergency_conditions` ALSO flagged
**three** repairable conditions as EmergencyTargets with
`suggested_action="CANCEL_AND_DELETE"`:

1. `no_exit_plan` (lines 241-248) — duplicate of remediation's RECREATE_EXIT_PLAN
2. `duplicate_exits` (lines 250-257) — duplicate of remediation's CANCEL_STALE_ORDERS with keep_one=True
3. `stale_exit_order` (lines 259-266) — duplicate of remediation's CANCEL_STALE_ORDERS

`scripts/autonomous_remediation.py` calls BOTH `remediate()` AND
`scan_emergency_conditions()` → `execute_emergency_close()`. They fire
in parallel. Remediation does the right thing (cancel, keep-one). Emergency
engine does CANCEL_AND_DELETE = `DELETE /v2/positions/{symbol}` = MARKET SELL.

### Tuesday timeline

| Time UTC | Event |
|---|---|
| 14:16 | morning-allocator placed 7 BUY brackets (v3.9.6 GTC). All filled within seconds. |
| 16:09 | Governor FLAT→GREEN @ +$484 P&L |
| **16:57** | morning-allocator triggered AGAIN (cron retry / watchdog). EXEC_TTL was 60 min, 161 min elapsed → re-executed plan. |
| 16:57 | v3.8.8 "open orders" pre-check returned EMPTY (orders already filled immediately on placement). Position pre-check WAS MISSING. → 3 duplicate brackets for SPY/QQQ/GLD placed. |
| 19:08:48 | remediation correctly CANCEL_STALE_ORDERS keep_one=True (cancels extras, keeps 1 OCO) |
| **19:08:50** | emergency_engine flagged `duplicate_exits` → `execute_emergency_close` → `DELETE /v2/positions/SPY,QQQ,GLD` → MARKET SELL. 3 positions liquidated. |
| 21:01 | Peak $920 → current -$429 = 146% giveback → governor RED_DAY_AFTER_GREEN, max_gross 1.50→0.25 |

### Three bugs, three fixes (v3.9.9)

**Bug B (P0)** — `shared/emergency_engine.py:241-266` removed. Lines now
contain v3.9.9 comment explaining: repairable states (no_exit_plan,
duplicate_exits, stale_exit_order) are handled non-destructively by
`shared/remediation.py`. `scan_emergency_conditions` retains: hard_loss,
option_near_dte, defensive_mode, daily_drawdown. **Invariant test**
in `tests/architecture_vnext/test_emergency_engine_v399_invariant.py`
(5 tests) prevents regression — asserts no EmergencyTarget ever has
reason in {no_exit_plan, duplicate_exits, stale_exit_order}.

**Bug A (P0)** — `shared/allocator.py::_exec_buy` extended with POSITION
pre-check via `_fetch_single_position(sym)` BEFORE the v3.8.8 open-orders
check. Skips BUY if `abs(current_qty - target_qty) / target_qty < 0.10`
(within 10% rebalance threshold). Plus `scripts/execute_allocation_plan.py`:
`EXEC_TTL_MIN` 60 → **360 min** (covers full trading session). 5 tests
in `tests/aggressive/test_allocator_v399_position_precheck.py`.

**Bug C (P1)** — `learning-loop/adapter.py:407-425` PR #10 macro fallback
DECOUPLED from `_reset_options_bias_if_no_data` gate. Previous wire-in
was dead code because the reset gate returned False when current_bias
was already None (the most common case). Now: independent check on
`current_bias is None AND options-momentum.trades_7d < 3`. 2 new tests
in `learning-loop/test_adapter.py::TestOptionsBiasMacroFallbackWiredIntoAdapt`.

### Shared root cause (Bug A + Bug B)

**System lacked idempotency on Alpaca state.** Bug A: allocator checked
its own pending orders but not the actual position state. Bug B:
remediation treated "duplicate" as emergency rather than as repairable
artifact. v3.9.6 was a POINT FIX (RECREATE_EXIT_PLAN); v3.9.9 introduces
an INVARIANT: `EMERGENCY_CLOSE` is forbidden for reasons in
{no_exit_plan, duplicate_exits, stale_exit_order}. Regression test
enforces this.

### Verification plan (Wednesday 2026-05-28)

This time the v3.9.9 production test is Wednesday (Tuesday was Day 0).
Same checkpoints as Monday's plan plus:
- Watch for `duplicate_exits` flag from health-check — should trigger
  CANCEL_STALE_ORDERS (keep_one), NOT EMERGENCY_CLOSE
- If allocator triggers twice in session, second run should log
  `BUY skipped: position SPY already exists qty=X target=Y (within 10%
  rebalance threshold)` for each held symbol
- Audit JSONL `journal/autonomy/2026-05-28.jsonl` MUST NOT contain any
  `decision_type=EMERGENCY_CLOSE` events with reason in {duplicate_exits,
  no_exit_plan, stale_exit_order}.

Success criteria: ≥1 allocator retrigger in session (typical) + zero
EMERGENCY_CLOSE for repairable reasons + invariant test stays green
on every PR.
