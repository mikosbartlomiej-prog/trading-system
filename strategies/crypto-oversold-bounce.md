# Crypto Oversold Bounce — strategy

**Version:** v3.14.0 (doc shipped 2026-06-02, closes audit-board DOC-003)
**Status:** ACTIVE in `learning-loop/state.json::crypto-oversold-bounce.enabled=true`
**Monitor:** [crypto-monitor/monitor.py](../crypto-monitor/monitor.py)
**Code path:** `check_crypto_signal()` — first decision branch (BEFORE predator/breakout filters)
**Strategy tag:** `crypto-oversold-bounce` (in `client_order_id`)
**Universe:** 11 coins in `COIN_TIERS` — BTC/USD, ETH/USD (Tier 1) + 9 Tier 2 alts

## Why this strategy exists

The original `crypto-momentum` strategy (breakout + RSI 50–65 + volume) was
designed to catch sustained momentum entries. It works on breakouts, but it
**systematically misses deep-oversold mean-reversion setups** — when BTC/ETH
RSI drops below 30 after a multi-day sell-off, the predator bracket
(`24h_move ∈ [3%, 15%]`) blocks the entry because the 24-hour move is
negative or flat (not in the bracket's "active move" range).

This pattern was observed for **45 consecutive days** in production
(2026-04 → 2026-05): BTC RSI dropped to 22, ETH RSI to 19.5, but
`crypto-momentum` placed zero orders because the bracket filter ruled them
out. LLM Senior PM flagged this on 9 of those days. v3.11.3 added the
oversold-bounce alternative path. v3.13.3 relaxed the entry condition
(strict 1-bar reversal → 3-bar stabilization) after another zero-fire
window. v3.14.0 ships this design doc.

## Hypothesis (market logic)

Deep-oversold crypto markets exhibit mean-reversion behavior on the 1-hour
timeframe. After a forced-selling cascade resolves (1–3 days), liquidity
returns and the asset re-bids. Setups where:

1. RSI(14) ≤ 30 (deep oversold by Wilder's definition)
2. 24-hour move ≥ -10% (the cascade has not blown out entirely — we want
   distress, not catastrophe)
3. Average of last 3 hourly closes ≥ close from 3 hours ago (the bleeding
   has stopped; price is stabilizing horizontally)
4. Volume ≥ 25% of normal (some buying interest is back; not a dead-tape
   gap-down)

…tend to print short-term bounces of +3% to +10% over 12–48 hours.

This is NOT a trend strategy — it does not require continued upside. It
plays the bounce. The 1.5× wider stop (vs `crypto-momentum`) gives the
setup room to breathe.

## Entry conditions (code reference)

[crypto-monitor/monitor.py::check_crypto_signal](../crypto-monitor/monitor.py)
sections marked `# ── OVERSOLD-BOUNCE entry`:

```text
1. RSI(14) ≤ OVERSOLD_BOUNCE_RSI_MAX                 (default 30)
2. 24h_move_pct ≥ OVERSOLD_BOUNCE_MIN_MOVE_PCT       (default -10%)
3. len(closes) ≥ OVERSOLD_BOUNCE_REVERSAL_BARS + 1   (default 3 + 1 = 4 bars)
4. avg(closes[-3:]) ≥ closes[-4]                     (3-bar stabilization)
5. current_volume > avg_vol_20 × (vol_mult × OVERSOLD_BOUNCE_VOL_MULT_FLOOR)
                                                      (default 25% of vol_mult)
6. NOT (tier == 2 AND btc_1h_change ≤ BTC_DOMINANCE_GUARD_PCT)
                                                      (alt-long protection)
```

All 6 must be true. Mind the precedence: oversold-bounce is checked FIRST,
BEFORE the predator filter, so it can fire even when 24h_move is outside
the predator bracket.

## Exit conditions

Same as `crypto-momentum` with one modification:

- **Stop-loss:** `current_price * (1 - sl_pct * 1.5)` — 1.5× wider than
  normal predator SL (room to breathe for the bounce setup)
- **Take-profit:** `current_price * (1 + tp_pct)` — same as predator
- **Time-decay exit:** governed by `exit-monitor` `CRYPTO_DECAY_HOURS` =
  48 hours (v3.0). If position has not progressed by then, close.
- **Trailing stop:** governed by `exit-monitor` (8% off peak, 12h min hold)

Exit-monitor handles all SL/TP since Alpaca paper crypto does not support
bracket orders (no broker-side OCO).

## Sizing

Per tier in `COIN_TIERS`:

- **Tier 1 (BTC/ETH):** `size_long` = $8k (BTC), $4k (ETH)
- **Tier 2 (alts):** `size_long` = $2.5k each (predator quick-win mode)

After v3.11.3 LLM Senior PM 1.3× boost (when ETH RSI ≤ 30 + BTC RSI ≤ 45):
sizes scaled 1.3×.

After v3.9.8 deep-oversold boost (when ETH RSI ≤ 25 + BTC RSI ≤ 45):
sizes scaled 1.5×.

## Risk guards (v3.14.0)

The signal must clear ALL these gates BEFORE Alpaca order placement:

1. **Trade window** (`shared/instrument_windows.py::can_trade_now`) — crypto
   24/7 default-allow, per-symbol pause respected.
2. **IntradayProfitGovernor** (`shared/intraday_governor.py`) — blocks new
   entries when FSM is DEFEND_DAY / RED_DAY_AFTER_GREEN.
3. **PDT guard** (`shared/pdt_guard.py`) — crypto exempt (24/7).
4. **Concentration** (`shared/risk_guards.py::concentration_ok`) — 40% per
   ticker cap on equity.
5. **Risk-officer** (`shared/risk_officer.py::evaluate_trade`) — 9 hard
   checks including whitelist, SL exists, R:R ≥ 1.5, BP available.
6. **Confidence gate** (v3.14.0) — `confidence_inputs` computed by
   `shared/confidence_builder.py`, evaluated in `risk_officer`. BLOCKs
   when total confidence < 0.50.
7. **Alt-position cap:** `MAX_ALT_POSITIONS = 3` simultaneous Tier 2
   positions (predator philosophy: focus, not spray).
8. **LLM Curator** (Cloudflare Routine, fail-soft) — optional final
   gate; falls through to heuristic when budget exhausted.

## Empirical state

| Metric | Value | As of |
|---|---|---|
| Trades placed (lifetime) | 0 | 2026-06-02 |
| State `enabled_at` | (none yet — v3.13.3 relaxation just deployed) | — |
| Strict-version disabled? | v3.11.3 strict 1-bar reversal — replaced 2026-06-02 | — |

Observation window: 14 days post v3.13.3 relaxation. If still 0 fires by
2026-06-16 despite BTC/ETH RSI dipping below 30 in that window → flagged
as "broken pipeline, not market regime" and disabled (or further
relaxed). Tracking via:

```python
# learning-loop/analyzer.py::_flag_silent_strategies
# crypto-oversold-bounce flagged SILENT after 21 days with 0 fires
# (v3.11 zombie-prune logic, PIPELINE_FAILURE classification)
```

## Do-NOT-trade conditions

- **`OPTIONS_ENABLED=false`** — does NOT affect this (crypto strategy)
- **`crypto-oversold-bounce.enabled=false`** in `state.json` — explicit
  operator pause overrides everything
- **`crypto-oversold-bounce.paused_until > now`** — temporary pause
- **`tier == 2 AND btc_1h_change ≤ -3%`** — BTC crash, alts correlated;
  skip alt-long until BTC stabilizes
- **`SAFE_MODE_ACTIVE`** — all new entries blocked regardless of
  strategy

## Backtest evidence

NOT YET BACKTESTED. This strategy was added 2026-05-30 as a hypothesis
from LLM Senior PM (recurring "BTC RSI 22 = high bounce probability"
observation across 9 daily reports). It currently runs **without**
`edge_validator` gate (`EDGE_GATE_ENABLED=false` default — operator
opt-in). Backtest scheduled as part of v3.15 READINESS-2 sweep.

Until backtest validates edge:
- Manual operator review every 7 days for first 4 weeks
- Auto-flagged in `session_report` when fires (even 1 trade)
- Conservative sizing held at current values (no boost beyond LLM-rendered
  1.5× ceiling)

## Related findings

- **STRAT-002** (audit-board 2026-06-02, P1 NEEDS_FIXES) — 0 trades in
  45 days; v3.13.3 relaxation addresses; 14-day observation window
  active.
- **STRAT-003** (audit-board 2026-06-02, P1 NEEDS_FIXES) — `EDGE_GATE`
  remains DISABLED for this strategy; flip after backtest validation.

## Operator notes

- If LLM Senior PM flags this strategy as silent for >21 days → check
  `learning-loop/state.json::crypto-oversold-bounce.placed_lifetime` and
  decide pipeline_failure vs no_edge classification (v3.11.1 policy).
- Do NOT re-enable strict 1-bar reversal (`OVERSOLD_BOUNCE_REVERSAL_BARS=1`)
  without backtest evidence — that was the dormancy root cause for 45
  days.
- v3.14.0 wires `confidence_inputs` for this strategy. Watch for
  unexpected BLOCKs in production (means primary_score normalization
  needs tuning — see `_primary_score_for("crypto-oversold-bounce", rsi)`).
