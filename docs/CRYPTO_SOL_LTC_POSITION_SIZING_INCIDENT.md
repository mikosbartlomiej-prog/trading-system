# Crypto SOL/LTC Position Sizing Incident Report (v3.25)

**Date:** 2026-06-08
**Author:** v3.25 sprint
**Status:** PARTIAL_ROOT_CAUSE_IDENTIFIED_REMAINING_DETAILS_REQUIRE_MORE_LOGS

## What happened

On 2026-06-06 the system executed two large `sell_to_close` events:

| Symbol | Qty closed | Avg fill | Sell amount | Reconstructed cost basis | Realized P/L approx |
|---|---:|---:|---:|---:|---:|
| SOLUSD | 451.353798 | $60.070217 | $27,112.92 | $29,964.07 | **-$2,851.15** |
| LTCUSD | 675.170322 | $40.317423 | $27,221.13 | $29,964.03 | **-$2,742.90** |
| **Combined** | | | | **~$59,928** | **-$5,594.06** |

`~$59,928` combined cost basis is **~60% of the $100k paper equity baseline**, with each leg ~30%. v3.24 reattribution confirmed this is the **primary drawdown source** (-$5,594.06 of the -$5,741 reported drop).

## Existing controls (what was in place before v3.25)

A grep + read survey of the crypto buy path:

| Control | Where | Behavior | Effective vs. SOL/LTC ? |
|---|---|---|---|
| `MAX_ALT_POSITIONS = 3` | `crypto-monitor/monitor.py:194` | Cap on **count** of open Tier-2 alt positions | **Insufficient** — caps how many alts but not their dollar size |
| `has_open_position(symbol)` | `crypto-monitor/monitor.py:709` | Binary check: skip BUY if any qty>0 | **Insufficient** — once a position drops to dust or returns 404, the next cron tick re-opens it |
| `portfolio_risk.evaluate` → `max_crypto_exposure_pct` | `shared/portfolio_risk.py:345-351`, profile `AGGRESSIVE_PAPER = 25%` | Hard aggregate crypto exposure cap | **Partially effective** — should have stopped at 25%; either (a) repeated buys evaluated each against a pre-tick exposure snapshot that fell short of the cap because broker state was stale, OR (b) the cap was not re-checked at every buy submission, OR (c) the buy path silently bypassed the gate in some sessions |
| `_portfolio_risk_gate` in `place_crypto_order` | `shared/alpaca_orders.py:580-588` | Per-order portfolio-level check | Same caveat as above |
| Trade-window / PDT / intraday governor gates | `place_crypto_order` | Active | Not relevant to sizing |

## What was missing

No code path enforced any of:

- **per-symbol crypto dollar exposure cap** (only a count cap on Tier-2 alts)
- **pending-order pre-check** (next cron could fire a BUY while a prior limit was still resting)
- **min cooldown between consecutive buys of the same crypto symbol**
- **max laddering buys per symbol per day**
- **recent-realized-loss cooldown** (closing a position at -9% should temporarily block fresh entries into the same symbol)
- **drawdown-guard hard-block on crypto buys** specifically (the existing daily drawdown halts apply to entries broadly, but evidence shows crypto buys still occurred close enough to the close that the close had to flatten ~$60k)

These gaps are the proximate cause of how SOL and LTC could climb to ~30% equity each via repeated ~$2,500 entries without anything intervening.

## Root-cause classification (per v3.25 spec)

| Tag | Verdict | Evidence |
|---|---|---|
| `CRYPTO_REPEATED_BUY_LADDERING_INTENDED_BUT_UNCAPPED` | **CONFIRMED** | Tier-2 sizing is $2,500/buy (`COIN_TIERS`). Reaching $30k requires ~12 separate fills per symbol. Each individual buy was within aggregate cap; no per-symbol dollar cap, no cooldown |
| `CRYPTO_REPEATED_BUY_RUNAWAY_LOOP` | **NOT CONFIRMED** | `has_open_position` binary check is in place; would block obvious runaway. SOL/LTC growth fits intended (per-cron) laddering, not a runaway loop |
| `CRYPTO_POSITION_ALREADY_OPEN_BUT_BUY_REPEATED` | **PARTIAL** | `has_open_position` is binary; once a position exists, subsequent buys should be skipped. But repeated buys of $2,500 evidently still happened — likely because dust / Alpaca-404 races made `has_open_position` return False between fills, OR because the position was held continuously and the binary gate is the ONLY check (no laddering guard) |
| `CRYPTO_PENDING_ORDER_NOT_CONSIDERED` | **CONFIRMED** | No pending-order check in `execute_crypto_signal` / `place_crypto_order` / `crypto-monitor.run_scan`. A resting limit followed by a fresh cron tick could double up |
| `CRYPTO_MAX_SYMBOL_EXPOSURE_MISSING` | **CONFIRMED** | No per-symbol crypto dollar exposure cap anywhere |
| `CRYPTO_AGGREGATE_EXPOSURE_CAP_MISSING` | **PARTIAL** | `max_crypto_exposure_pct = 25%` exists in `portfolio_risk.py`. Either the cap held individually for each buy (sums of small additions sneaking past), or there's a wiring gap. Needs runtime evidence |
| `CRYPTO_DRAWDOWN_GUARD_TRIGGERED_TOO_LATE` | `CRYPTO_ROOT_CAUSE_REQUIRES_MORE_LOGS` | No runtime log of when guard activated relative to SOL/LTC accumulation |
| `CRYPTO_EXIT_POLICY_MARKET_CLOSE_WITHOUT_PRECHECK` | `CRYPTO_ROOT_CAUSE_REQUIRES_MORE_LOGS` | The 2026-06-06 close was a single ~$27k market sell per symbol — evidence of exit reason / risk gating prior to the close is not in local logs |
| `CRYPTO_ORDER_AUDIT_PATH_UNCLEAR` | `CRYPTO_ROOT_CAUSE_REQUIRES_MORE_LOGS` | `safe_close` events for SOL/LTC on 2026-06-06 not searched yet in this sprint |
| `CRYPTO_ROOT_CAUSE_REQUIRES_MORE_LOGS` | **CONFIRMED for timing** | Cron-by-cron accumulation timeline of SOL/LTC buys is not in local repo logs |

## What v3.25 ships

Hard guards that **cannot be bypassed** by repeated cron ticks even if the prior controls had race conditions:

- `shared/crypto_exposure_policy.py` — module-level constants for max aggregate, max per-symbol, max meaningful symbols, ladder limit, cooldown, recent-loss cooldown, plus an `evaluate_crypto_buy()` function returning a structured `CryptoBuyDecision`.
- `shared/crypto_exit_policy.py` — structured exit-reason enum + audit emission requirement, precision-close guard, dust exit operator decision.
- `shared/trading_unlock_readiness.py` — deterministic verdict gate. Default expected: `SIGNAL_SHADOW_UNLOCK_READY`; broker paper stays blocked.

Tests prove that the literal SOL/LTC pattern (12 × $2,500 buys per symbol, then 5-minute repeat) is blocked under defaults.

## What this report does NOT do

- Does NOT place orders.
- Does NOT close SOLUSD or LTCUSD (currently dust per v3.23.3.3 dashboard verification).
- Does NOT close ETHUSD or AVAXUSD (meaningful open positions).
- Does NOT enable broker paper or live trading.
- Does NOT reset starting_equity baseline.
- Does NOT lower drawdown guard.
- Does NOT infer or invent `client_order_id`.
- Does NOT fabricate realized P/L.
- Does NOT delete or hide audit logs.

Machine-readable companion:
[`learning-loop/position_reconciliation/crypto_sol_ltc_sizing_incident_latest.json`](../learning-loop/position_reconciliation/crypto_sol_ltc_sizing_incident_latest.json).
