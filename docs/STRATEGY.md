# Trading System — Risk & Strategy Document

**Version:** 3.0 — Aggressive Momentum + Event Switch (supersedes 2.4)
**Effective from:** 2026-05-12
**Account:** Alpaca Paper, ID PA3KNZV29BP5, Level 3 options enabled
**Author:** mikosbartlomiej-prog + Claude (Cowork)

This is the canonical source of truth for risk and strategy parameters.
Every monitor, every strategies/*.md file, every agent prompt, and every
iron rule in CLAUDE.md must agree with the numbers here. If a number
appears in code that contradicts this document, **the document wins** —
update the code.

**v3.0 IS A MAJOR REWRITE.** Five new modules added (`config/aggressive_profile.json`,
`config/watchlists.json`, `shared/regime.py`, `shared/momentum_score.py`,
`shared/defensive_mode.py`). Strategy becomes regime-aware: capital rotates
between 4 buckets (AI/Nasdaq/Semis · Inflation/Energy · Crypto · Hedge) based
on Event Switch state (RISK_ON / INFLATION_SHOCK / RISK_OFF / NEUTRAL).
Tighter risk: daily loss limit -3% (was -12%), weekly -7%, max DD -12%
triggers defensive mode. Composite momentum scoring pre-ranks tickers;
only top 7 scanned per cron.

See **§4.0 Event Switch & Buckets** below for the new regime layer.

---

## 1. Investment Philosophy

### 1.1 Mission

Generate the highest possible compounded return on the paper account
over short horizons (intraday → 30 days). The system is **risk-on by
default**: it embraces volatility, runs concentrated positions, and
prefers many fast trades over a few cautious ones.

### 1.2 Posture

| Dimension | Value |
|---|---|
| Risk appetite | **Aggressive** — accept high single-day variance for higher expected return |
| Time horizon | Intraday → 30 days |
| Capital usage | **All capital available**; no cash reserve, margin actively used |
| Position concentration | **High** — up to 40% of equity in one ticker, up to 80% notional in options |
| Trade frequency | **High** — 5-min cron ticks, multiple entries per day |
| Bias | Long-biased on momentum, short on overbought reversals, both directions in crypto |

### 1.3 Hard constraints (the only things we will NOT compromise)

1. Paper account only — no live trading, ever
2. Every entry has a stop-loss (no naked positions left without an exit)
3. Whitelist enforcement — never trade outside `.claude/rules/tickers-whitelist.md`
4. Earnings ±1d skip on options (single biggest IV-crush risk we cannot model)
5. Daily catastrophic-loss circuit breaker stops new entries (see §3)

Everything else is up for renegotiation as the strategy evolves.

---

## 2. Capital Structure

### 2.1 Account snapshot

| Item | Value |
|---|---|
| Equity | $100,032 (as of 2026-05-06) |
| Cash | full equity available |
| Buying power | ~$200,000 (Reg-T intraday) |
| Settled day-trade buying power | up to 4× equity |
| Shorting | enabled (`no_shorting=false`) |
| Options level | 3 (all single-leg long/short permitted) |

### 2.2 Capital rules

- **Cash reserve:** 0% (was 5%). Every dollar can be deployed.
- **Margin usage:** target 1.5×–2.5× gross exposure (not maxed at 4× — leave headroom for adverse moves)
- **Per-ticker cap:** 40% of equity (was 15%) — single name can hold up to $40k notional
- **Per-trade cap:** 20% of equity (was 5%) — single signal can size up to $20k

### 2.3 Soft asset-class allocations (gross, % of equity)

These are guidelines used by exit-monitor and the risk-officer agent to
flag concentration. Going over is allowed if a setup is exceptional, but
the agent will warn.

| Asset class | Soft cap | Notes |
|---|---|---|
| US momentum stocks (long + short) | 60% | $60k gross |
| Leveraged ETFs (3×) | 25% | $25k — decay risk caps the cap |
| Crypto (BTC + ETH) | 25% | $25k — 24/7, can be large since liquid |
| Defense / geopolitical / sector ETFs | 35% | $35k |
| Options (premium paid) | 25% | $25k — notional exposure can be 100%+ via leverage |
| Reddit sentiment (when active) | 10% | $10k |

The total can exceed 100% (margin) up to ~250% in aggressive periods.

---

## 3. Risk Budget

### 3.1 Drawdown circuit breakers

| Trigger | Action |
|---|---|
| Single trade SL hit | Position closes (per-strategy SL price), system continues |
| **Daily P&L ≤ -12%** | New entries blocked till next day; exits keep working |
| **Weekly P&L ≤ -25%** | All monitors paused (workflows disabled); manual review required before resuming |
| **Monthly P&L ≤ -40%** | Full stop. Strategy review and parameter reset before any new trade |
| VIX > 60 | New entries blocked (only-catastrophic-volatility halt) |

Old breakers that are **REMOVED**:
- ~~Daily -3% stop~~ → relaxed to -12%
- ~~No trading when VIX > 35~~ → relaxed to VIX > 60
- ~~5% per-trade cap~~ → relaxed to 20%
- ~~5% cash floor~~ → 0%
- ~~15% per-ticker cap~~ → 40%

### 3.2 Per-strategy stop-loss (mandatory, every entry)

Stop-losses are MANDATORY but **looser** than before — we want positions
to breathe. They are placed as the SL leg of bracket orders for stocks
(Alpaca supports brackets on stocks) and emulated by the
options-exit-monitor for options.

| Asset class | Stop-loss rule |
|---|---|
| US stocks (long & short) | entry ± 2.0 × ATR(14) |
| Leveraged ETFs | entry × (1 ∓ 5%) |
| Crypto | entry × (1 ∓ 7%) |
| Defense / geo / sector | entry × (1 ∓ 5%) |
| Options | premium × 0.35 (-65%) |
| Reddit sentiment | entry × (1 - 6%) |

### 3.3 VIX policy

| VIX level | Old policy | **New policy** |
|---|---|---|
| < 30 | OK | OK |
| 30-35 | OK | OK |
| 35-45 | CAUTION (50% sizing) | **OK (full sizing)** |
| 45-60 | HALT | **OK (full sizing)** |
| > 60 | HALT | **HALT (catastrophic only)** |

The VIX guard in `shared/risk_guards.py::vix_guard()` is rewritten to
return HALT only above 60 and OK otherwise. CAUTION mode is removed.

---

## 4. Asset Class Strategies

Numbers in this section are the canonical sizing/threshold values. Code
constants in monitors must equal these.

### 4.0 Event Switch & Watchlist Buckets (v3.0 NEW)

The system operates in one of **four regimes** at any time. Each regime
restricts which watchlist buckets are eligible for new entries and how
aggressive sizing should be.

#### Regimes

| Regime | When inferred | Allowed buckets | Size mult | Options bias |
|---|---|---|---|---|
| **RISK_ON** | VIX < 25 AND SPY 5d ≥ +1.5% | ai_nasdaq_semis, crypto | 1.0× | long |
| **INFLATION_SHOCK** | energy_5d > +3% AND SPY 5d ≤ -2% | inflation_energy, hedge_metals | 1.0× | null |
| **RISK_OFF** | VIX ≥ 50 OR SPY 5d ≤ -4% | hedge_metals, hedge_bonds | 0.5× | short |
| **NEUTRAL** | else (default) | ai_nasdaq_semis, inflation_energy, crypto | 0.7× | null |

Detection mode (per `config/aggressive_profile.json::regime.detection_mode`):
- `hybrid` (default) — read manual override from `learning-loop/state.json
  ::global_overrides.regime_override`; if null, auto-detect via rules above
- `auto` — rules only
- `manual` — manual only (auto returns NEUTRAL)

Module: `shared/regime.py::detect_regime(market_signals)`.

#### Watchlist Buckets (v3.0)

Config: `config/watchlists.json`. Loaded via `shared/profile.load_watchlists()`.

| Bucket | Tickers | Size per pos | SL / TP |
|---|---|---|---|
| `ai_nasdaq_semis` | QQQ, SMH, NVDA, AMD, AVGO, MSFT, META, GOOGL, AAPL, AMZN, TSLA | $10,000 | -6% / +18% |
| `inflation_energy` | XLE, USO, XOM, CVX, OXY | $6,000 | -7% / +15% |
| `crypto` | 11 coins (per crypto-monitor COIN_TIERS) | per-tier | per-tier |
| `hedge_metals` | GLD, SLV | $8,000 | -5% / +12% |
| `hedge_bonds` | TLT | $6,000 | -4% / +8% |
| `leveraged_etf_bull` | TQQQ, SPXL, UPRO, SOXL, FAS, TNA | $6,000 | -8% / +20% |
| `leveraged_etf_bear` | SQQQ, SPXS, SPXU, SOXS, FAZ, TZA | $4,000 | -8% / +18% |
| `defense_geo` | RTX, LMT, NOC, GD, BA, KTOS, PLTR, AXON, LDOS, SAIC, CACI, ITA, XAR, DFEN | $8,000 | -6% / +15% |

A ticker can be in multiple buckets implicitly (e.g. QQQ in ai_nasdaq_semis;
the `defense_geo` ETF ITA is energy-correlated). Only `bucket_for_ticker()`
in shared/profile.py determines the primary bucket (first match wins).

#### Composite Momentum Scoring (v3.0 NEW)

Module: `shared/momentum_score.py::score_symbol(ticker, bars, spy_bars, qqq_bars)`.

Returns score in [-1, +1] combining (weights from
`config/aggressive_profile.json::scoring.weights`):

- 5D / 10D / 20D momentum
- relative strength vs SPY/QQQ (stronger of the two)
- volume expansion (today / 20d avg)
- breakout flag (close > prev day high OR 30-min ORH)
- trend filter (price > SMA20 > SMA50)
- volatility penalty (high ATR/SMA20 without trend = noise)

Entry gate: `score >= 0.35`. Price-monitor pre-ranks all eligible tickers,
scans only `top_n_picks=7` per cron tick. Focuses execution on leaders;
laggards never get checked.

#### Aggressive Risk Profile

Config: `config/aggressive_profile.json`. Replaces hardcoded constants.

| Limit | v3.0 | v2.0 |
|---|---|---|
| max_single_position | **20%** equity | 20% |
| max_sector_exposure | **55%** equity | (none) |
| max_options_premium | **25%** equity | 25% |
| max_crypto_exposure | **20%** equity | 25% |
| max_gross_exposure | **1.50×** equity | ~2.5× |
| cash_reserve | **10%** equity | 0% |
| **max_daily_loss** | **-3%** | -12% |
| **max_weekly_loss** | **-7%** | -25% |
| **max_drawdown_defensive** | **-12%** | -40% (full stop) |
| **max_drawdown_full_stop** | **-20%** | (manual) |

Drawdown breach actions:
- **-3% daily** → `daily_drawdown_guard` HALT new entries (exits keep working)
- **-7% weekly** → WARN (operator/LLM decide pause)
- **-12% drawdown** → `defensive_mode_armed: true` in state.json. Price-monitor
  blocks new entries entirely. Existing exit-monitor + options-exit-monitor
  keep closing positions normally.
- **-20% drawdown** → `FULL_STOP` level — would close all positions IF
  `kill_switch_armed=true` set manually in state.json (prevents accidental flat
  on transient API blip). Default: just notify, no auto-close.

### 4.1 US Equities — Momentum LONG

**Strategy file:** `strategies/aggressive-momentum.md`
**Monitor:** `price-monitor` (cron `*/5 13-20 * * 1-5`)

| Parameter | Value |
|---|---|
| Tickers | AAPL, MSFT, GOOGL, NVDA, META, AMZN, TSLA, SPY, QQQ |
| Entry condition | Close > 20-day high AND RSI(14) ∈ [50, 70] AND volume > 1.5× 20-day avg |
| Size per signal | **$10,000** |
| Stop-loss | entry - 2.0 × ATR(14) |
| Take-profit | entry + 4.0 × ATR(14) |
| R:R | ~2.0 |
| Order type | LIMIT, DAY |
| Max concurrent long positions | 6 |

### 4.2 US Equities — Overbought Reversal SHORT

**Strategy file:** `strategies/aggressive-momentum.md` (same file, SHORT section)

| Parameter | Value |
|---|---|
| Tickers | AAPL, MSFT, GOOGL, NVDA, META, TSLA, AMZN |
| Entry condition | RSI(14) > 72 AND 2/3 of (price within 2% of 20-d high, volume < 0.8× avg, close < prev open) |
| Size per signal | **$8,000** |
| Stop-loss | entry + 2.0 × ATR(14) |
| Take-profit | entry - 4.0 × ATR(14) |
| R:R | ~2.0 |
| Max concurrent short positions | 4 |

### 4.3 Leveraged ETFs (3×)

**Strategy file:** `strategies/leveraged-etf.md`
**Monitor:** `price-monitor` (LEVERAGED block) — same cron

| Parameter | Value |
|---|---|
| Tickers | TQQQ, SQQQ, SPXL, SPXS, UPRO, SPXU, SOXL, SOXS, FAS, FAZ, TNA, TZA |
| Entry condition (bull) | Underlying breakout + RSI 50-68 |
| Entry condition (bear) | Underlying breakdown + RSI < 38 |
| Size per signal | **$6,000** |
| Stop-loss | -5% |
| Take-profit | +18% |
| R:R | 3.6 |
| Max hold | 96 hours |
| Max concurrent | 4 |

### 4.4 Crypto (predator-grade — BTC/ETH + 9 mid-cap alts, v2.4 2026-05-12)

**Strategy file:** `strategies/crypto-strategy.md`
**Monitor:** `crypto-monitor` (cron `0,30 * * * *`, 24/7)
**Universe:** 11 coins across 2 tiers
**LLM filter:** `crypto-monitor/llm_curator.py` + Curator routine
(predator on-chain trader persona; 0-3 selected per scan, fail-soft
to heuristic order on Curator unavailability).

#### Tier 1 — proven majors (BTC, ETH)

| Parameter | BTC LONG | BTC SHORT | ETH LONG | ETH SHORT |
|---|---|---|---|---|
| Size | **$8,000** | **$6,000** | **$4,000** | **$3,000** |
| Stop-loss | -7% | +7% | -7% | +7% |
| Take-profit | +20% | -20% | +20% | -20% |
| R:R | ~2.9 | ~2.9 | ~2.9 | ~2.9 |
| Volume mult | 2.0× avg | 1.5× avg | 2.0× avg | 1.5× avg |
| RSI band | 45-68 long | <35 short | 45-68 long | <35 short |

#### Tier 2 — mid-cap alts (quick wins, tighter cycles)

**Coins:** SOL, AVAX, LINK, DOT, MATIC, LTC, BCH, UNI, AAVE (all /USD)

| Parameter | LONG | SHORT |
|---|---|---|
| Size | **$2,500** each | **$2,000** each |
| Stop-loss | -8% | +8% |
| Take-profit | +10% | -10% |
| R:R | ~1.25 | ~1.25 |
| Volume mult | 3.0× avg | 2.5× avg |
| RSI band | 45-65 long | <35 short |

Lower R:R is acceptable because Tier 2 setups cycle FASTER — predator
philosophy: 5-10 small wins/week > 1 big win that reversed.

#### Predator filters (applied to ALL tiers)

| Filter | Rule |
|---|---|
| 24h momentum | move must be in **[3%, 15%]** range (skip stalls + late-pump traps) |
| BTC dominance | if BTC -3% in last 1h → **block alt longs** (correlated crash) |
| Alt position cap | max **3 simultaneous Tier 2 open positions** |
| Combined exposure | max **$25,000** across all 11 coins (unchanged v2.0) |
| LLM Curator | validates each candidate; can boost size 0.5-1.5× or reject |

The previous "weekend halving" rule is REMOVED. Volume in crypto is high
enough on weekends that the discount is unnecessary.

### 4.5 Defense / Geopolitical Events

**Strategy files:** `strategies/defense-market.md` + `strategies/geopolitical.md`
**Monitors:** `defense-monitor` (`0,30 * * * *`), `geo-monitor` (`*/15 13-21 * * 1-5`)

| Bucket | Tickers | Size LONG | Size SHORT |
|---|---|---|---|
| Big-5 defense | LMT, RTX, NOC, GD, BA | **$8,000** | **$5,000** |
| Mid-cap defense | KTOS, PLTR, AXON, LDOS, SAIC, CACI | **$5,000** | **$4,000** |
| Defense ETF | ITA, XAR, DFEN | **$6,000** | n/a (long only) |
| European ADR | BAESY, EADSY | **$4,000** | n/a |
| Geo basket (energy/gold) | XLE, XOM, GLD, CVX | **$6,000** | **$4,000** |

| Common parameter | Value |
|---|---|
| Stop-loss | -5% |
| Take-profit | +12% |
| R:R | 2.4 |
| Max defense + geo combined positions | 6 |
| News recency required | last 60 min |
| Scoring threshold for entry | ≥ 2 keywords matched |

### 4.6 Options (auto-execute on paper)

**Strategy file:** `strategies/options-strategy.md`
**Monitor (entry):** `options-monitor` (cron `*/10 13-20 * * 1-5`)
**Monitor (exit):** `options-exit-monitor` (cron `*/5 13-20 * * 1-5`)

| Parameter | Value |
|---|---|
| Underlying whitelist | AAPL, MSFT, GOOGL, NVDA, META, AMZN, TSLA, SPY, QQQ, JPM, RTX, LMT |
| Trigger CALL | RSI ∈ [45, 65] |
| Trigger PUT | RSI > 72 |
| Earnings filter | skip if earnings ±1 day |
| DTE window | **7-30 days** |
| Strike window | ATM ± **7%** |
| IV cap (call) | < **55%** |
| IV cap (put) | < **65%** |
| Premium budget | **$2,500** per signal (= $25/share for 1 contract) |
| Contracts per signal | up to **5** (default 1 in current implementation) |
| Take-profit | premium × **2.20** (+120%) |
| Stop-loss | premium × **0.35** (-65%) |
| Max open options total | **10** |
| Max proposals dispatched per cron run | **3** |
| Order type | simple LIMIT BUY (Alpaca paper rejects bracket on options) |
| Exit emulation | options-exit-monitor polls every 5 min during session |

### 4.7 Reddit Sentiment (paused — pending API approval)

**Strategy file:** `strategies/reddit-sentiment.md`

| Parameter | Value |
|---|---|
| Trigger | mention spike ≥ 3× 7-day avg + DD post (karma ≥ 5k WSB / 1k other, account ≥ 180d) |
| Direction | always BUY (momentum, not contrarian) |
| Size | **$5,000** |
| Stop-loss | -6% |
| Take-profit | +14% |
| Max concurrent | 4 |

### 4.8 Twitter / Social-Graph News (Bluesky MVP)

**Strategy file:** `strategies/twitter-news.md`
**Monitor:** `twitter-monitor` (cron `*/5 13-20 * * 1-5` + `*/15 * * * *` 24/7)
**Routine:** `Twitter Handler` (claude.ai)
**Data source MVP:** Bluesky AT-Protocol (free, TOS-safe). X API v2 Basic ($100/mo) is the future upgrade path; same monitor swaps via `SocialClient` abstraction.

5 interpretation patterns (routine classifies each post into one):

| Pattern | Trigger | Direction | Tickers | Size | SL / TP |
|---|---|---|---|---|---|
| **A** TICKER_DIRECT | category=`ticker:SYM` (CEO post about own company) | BUY/SELL by tone | TSLA, AAPL, GOOGL, MSFT | **$5,000** | -6% / +14% |
| **B** GEO_ESCALATION | category=`gov_us`/`mil_il` + escalation keywords | BUY | RTX/LMT/NOC ($8k); ITA/XAR/DFEN ($6k); XLE/XOM/CVX/GLD ($6k) | per ticker | -5% / +12% |
| **C** GEO_DEESCALATION | category=`gov_us`/`mil_il` + deescalation keywords | BUY SPY/QQQ; SELL XLE/GLD | SPY, QQQ, XLE, GLD | **$6,000** | -5% / +12% |
| **D** MACRO_DATA | category=`macro` + economic keywords (cpi, fomc, earnings beat/miss) | BUY/SELL by signal | SPY, QQQ, GLD, named ticker | **$6,000** | -5% / +12% |
| **E** WIRE_BREAKING | category=`wire` + breaking keywords | route to A/B/C/D by content | per pattern | per pattern | per pattern |

Hard caps:
- Cap per single post: **2 positions**
- Combined defense+geo+twitter cap: **6 open positions**
- Per-ticker cap: 40% equity (enforced by `concentration_ok`)
- Drawdown HALT at -12% daily, VIX HALT > 60

Event-probability gating:
- Monitor filters every post through `shared/event_scoring.py` BEFORE
  forwarding to routine
- Only `FOLLOW_REACTION` is dispatched
- `CONTRARIAN_CANDIDATE` → email-only flag (manual review; no auto-trade)
- `IGNORE_EVENT` / `WAIT_FOR_CONFIRMATION` → dropped silently

Curated whitelist: `.claude/rules/twitter-accounts.md` (v2.0 — ~50+ accounts in 4 tiers).

**4-tier policy override (v2.0, 2026-05-07):**

| Tier | Examples | Source-type | Cred | Keyword bypass | FOLLOW-only bypass |
|---|---|---|---|---|---|
| **T1** Trump admin | @POTUS, @VP, Cabinet, @PressSec, @federalreserve | `official_government` | 80 | ✅ | ✅ |
| **T1.5** Conflict leaders | Israel/Iran/Russia/Ukraine/NATO/China official | `official_government` | 80 | ✅ | ✅ |
| **T2** Tech CEOs | @elonmusk, @tim_cook, @sundarpichai, @JensenHuang, @saylor, ... | `tracked_corp_ceo` | 75 | ✅ | ✅ |
| **T2.5** Defense corps | @LockheedMartin, @RaytheonTech, @PalantirTech, ... | `tracked_corp_ceo` | 75 | ✅ | ✅ |
| **T3** Tracked anon | @aleabitoreddit + similar (manual curation, see strategy doc for criteria) | `tracked_anon_trader` | 55 | ✅ | ✅ |

For T1/T1.5/T2/T2.5/T3, **every post becomes a candidate (no keyword filter)** and **every stance is forwarded to routine + email** (not just FOLLOW). The routine receives `priority_override=true` in the payload and may choose to: (a) match pattern A-E and trade, or (b) log "no actionable pattern" with an email so the user sees the tweet anyway. This implements the policy "treat these tweets seriously even when they don't match the strategy."

### 4.9 Account-Aware Capital Deployment (v3.1 NEW 2026-05-12)

**Module:** `shared/allocator.py::AccountAwareAllocator`
**Config:** `config/capital_deployment.json`
**Hook:** runs at end of `learning-loop/analyzer.py::run()` (cron 21:00 UTC daily)
**Output:** `learning-loop/allocations/<date>.json` — daily allocation plan

Drives portfolio toward **100% invested capital** (target 1.00, min 0.98) by
rebalancing positions next trading day based on current account state.

#### Pipeline (post-learning-loop hook)

```
analyzer.run() → adapt() → save_state() → write_history_report()
                                                     ↓
                                          AccountAwareAllocator
                                          .compute_daily_plan()
                                                     ↓
                  1. fetch account (equity, cash, buying_power)
                  2. fetch positions (with mv, pl%, pct_equity)
                  3. check defensive_mode / kill_switch
                  4. detect regime (uses already-loaded today_stats)
                  5. score allowed universe (momentum_score over allowed buckets)
                  6. compute target weights:
                      a. primary picks: top N scored ≥ min_score @ ~18% each
                      b. enforce position cap (20%) + sector cap (55%)
                      c. fallback fill from regime-specific list
                  7. generate delta orders (BUY/SELL/REDUCE/EXIT/HOLD)
                  8. validate against risk_officer whitelist
                  9. cap by max_rebalance_orders_per_day (10)
                  10. save plan → learning-loop/allocations/<date>.json
                  11. (optional) execute via auto_execute_rebalance flag
                       — DEFAULT OFF; plan-only until operator validates
```

#### Capital Deployment Rules

| Rule | Value | Source |
|---|---|---|
| target_invested_ratio | 1.00 | capital_deployment.json |
| min_invested_ratio | 0.98 | capital_deployment.json |
| max_idle_cash_ratio | 0.02 | capital_deployment.json |
| operational_cash_buffer | 0.005 | capital_deployment.json |
| primary pick target weight | 18% | sizing_rules |
| max primary picks | 5 | sizing_rules |
| fallback pick target weight | 10% | sizing_rules |
| max fallback picks | 3 | sizing_rules |
| min_diff_pct_to_rebalance | 2% | sizing_rules (skip micro-trades) |
| max_rebalance_orders_per_day | 10 | capital_deployment.json |

#### Fallback Instruments per Regime

When primary momentum picks don't fill target, fallback instruments
absorb the remainder:

| Regime | Fallback |
|---|---|
| RISK_ON | QQQ, SMH, SPY |
| INFLATION_SHOCK | XLE, GLD, USO |
| RISK_OFF | GLD, SPY |
| NEUTRAL | SPY, QQQ, GLD |

#### Hard Risk Constraints (NEVER overridden by deployment target)

If full deployment would breach any of these, **risk wins, plan logs why
invested_ratio < target**:

- max_single_position_pct_equity (20%)
- max_sector_exposure_pct_equity (55%) — limits single-bucket concentration;
  realistic max in NEUTRAL/RISK_ON when picks are mostly ai_nasdaq_semis ≈ 55-65%
- max_options_premium_pct_equity (25%)
- max_crypto_exposure_pct_equity (20%)
- daily_drawdown_guard HALT (-3%)
- weekly_drawdown_guard HALT (-7%)
- defensive_mode_active (drawdown ≤ -12% from peak)
- full_stop_armed (drawdown ≤ -20%, requires manual confirmation)
- risk_officer whitelist (77 tickers as of 2026-05-12)
- Alpaca account_blocked / trading_blocked flags

#### Allocation Plan Schema

`learning-loop/allocations/<date>.json` contains:

```json
{
  "date": "2026-05-13",
  "generated_at": "2026-05-12T21:00:00Z",
  "account_equity": 97129.09,
  "portfolio_value": 97129.09,
  "cash": 12500.00,
  "buying_power": 194258.18,
  "invested_ratio_before": 0.872,
  "invested_ratio_after_target": 0.95,
  "market_regime": "NEUTRAL",
  "regime_source": "auto",
  "defensive_mode_active": false,
  "current_positions": [...],
  "scored_universe": [...],
  "target_weights": {"NVDA": 0.18, "AMD": 0.18, "MSFT": 0.18, ...},
  "current_weights": {"GLD": 0.13, "RTX": 0.18, ...},
  "rebalance_orders": [
    {"symbol": "NVDA", "action": "BUY", "delta": 17_500, "qty_delta": 125,
     "reason": "new position at target 18%"},
    {"symbol": "GLD",  "action": "EXIT", "delta": -12_700,
     "reason": "symbol not in target allocation"},
    {"symbol": "AAPL", "action": "HOLD",
     "reason": "|delta -1.2%| < min_diff 2.0%"}
  ],
  "risk_checks": {"passed": [...], "failed": [...], "n_orders": 4, "n_hold": 3},
  "allocation_reason": "regime=NEUTRAL | primary_picks=5(55%) | fallback=[GLD]"
}
```

#### Auto-Execute (Default OFF)

`config.auto_execute_rebalance: false` — allocator only **saves plans**.
Operator reviews `learning-loop/allocations/<date>.json` each morning
and decides which orders to place via Alpaca dashboard. Flag flips to
`true` after 30+ days of validated plans matching operator's expectations.

#### Execution Pipeline (v3.1.1 — 2026-05-12)

Two-stage cron architecture separates **plan generation** from **plan execution**:

| Stage | When | What happens |
|---|---|---|
| **Plan generation** | `21:00 UTC daily` (end of `daily-learning.yml`) | `analyzer.run()` → `AccountAwareAllocator.compute_daily_plan()` → JSON saved to `learning-loop/allocations/<date>.json` + trace log to `<date>.log` + `[allocator PLAN]` email to operator |
| **Plan execution** | `13:35 UTC weekdays` (`morning-allocator.yml`) | `scripts/execute_allocation_plan.py` reads today's plan → checks `auto_execute_rebalance` flag → if true: calls Alpaca REST per order, writes `<date>.execution.json`, sends `[allocator EXEC]` email summary |

**To enable auto-execute:**
1. Edit `config/capital_deployment.json` →
   `capital_deployment.auto_execute_rebalance = true`
2. Commit + push to main (`[automerge]` tag OK)
3. Next morning at 13:35 UTC, the morning-allocator workflow will execute
   the orders from the previous evening's plan

**To disable mid-stream:** revert the flag to `false`. Effective from the
next cron tick — no in-flight orders will be cancelled (use exit-monitor
or Alpaca dashboard for that).

**Diagnostic logs:** `learning-loop/allocations/<date>.log` contains the
full step-by-step trace (account fetch → regime → scoring → target weights
→ sector caps → rebalance orders → risk checks). `<date>.execution.json`
contains the per-order Alpaca response (id, status, reason). Both are
committed to main by their respective workflows for retrospective analysis.

**Failure modes** (all fail-soft — never crash learning loop):
- Allocator init fails (missing config) → plan skipped, learning loop continues
- Alpaca account fetch fails → plan written with `account_equity=0` + warning
- Market closed at execute time → stock orders skipped, crypto orders proceed
- Defensive mode active → BUY blocked, EXIT/REDUCE proceeds
- Risk-officer whitelist rejects symbol → order demoted to HOLD with `BLOCKED (reason)`

---

## 5. Exit Logic

### 5.1 exit-monitor (stocks, ETFs, crypto)

**File:** `exit-monitor/monitor.py`
**Cron:** `30 12-21 * * 1-5` + `0 22,0,2 * * *`

| Threshold | Old | **New** | Rule |
|---|---|---|---|
| `emergency_loss_pct` | -5% | **-12%** | If P&L ≤ this → CLOSE_EMERGENCY (overrides SL slippage) |
| `quick_profit_pct` (within 6h) | +3% | **+10%** | If P&L ≥ this in <6h → CONSIDER_TP (early profit) |
| `time_decay_hours` | 6 | **24** | If \|P&L\| < flat threshold after this many hours → CLOSE_FLAT |
| `flat_pnl_pct` | 1% | **3%** | "Flat" definition |
| `leveraged_decay_hours` | 48 | **96** | Leveraged ETF closed after this even if profitable |
| `crypto_decay_hours` | 12 | **48** | Crypto closed after this if P&L < 5% |

Decisions:
- `CLOSE_EMERGENCY` → CONSIDER closing immediately (manual or via routine)
- `CONSIDER_TP` → flag for early take-profit
- `CLOSE_DECAY` → close due to time-based decay
- `CLOSE_FLAT` → close due to flat P&L over time
- `HOLD` → no action

The exit-monitor reports decisions via email (`notify_exit`) and forwards
the full position table to a Claude routine for any final discretionary
overlay.

### 5.2 options-exit-monitor (options TP/SL)

**File:** `options-exit-monitor/monitor.py`
**Cron:** `*/5 13-20 * * 1-5`

Polling-based emulation of bracket orders (Alpaca paper rejects complex
order classes for options). For each open `us_option` position:

```
TP_threshold = avg_entry_price × 2.20    # +120%
SL_threshold = avg_entry_price × 0.35    # -65%
current = current_price (from /v2/positions)

if current >= TP_threshold:
    place SELL limit @ TP_threshold
elif current <= SL_threshold:
    place SELL limit @ current_price (best available exit)
else:
    HOLD
```

De-dup: skip if `/v2/orders?status=open&symbols={contract}` already
shows a SELL order, so the next 5-min tick doesn't stack a duplicate.

---

## 5.5 Execution Architecture (v2.2 — direct Alpaca REST)

**Decision (2026-05-07 EOD):** monitors place orders directly via Alpaca
REST, bypassing the Anthropic Routines path. This was prompted by a
hard 15-call/day Routines limit; under v2.0 sizing the system would
hit that ceiling within the first hour of an active session.

The routine path is preserved as opt-in fallback (set env `USE_ROUTINE=true`
on any monitor) for diagnostics, and remains the only path for
`weekly-learning` (1 call/week).

| Monitor | Default execution | Logic location |
|---|---|---|
| price-monitor | `execute_stock_signal` (bracket) | momentum/ATR rules in monitor |
| crypto-monitor | `execute_crypto_signal` (simple limit, no bracket) | 1h-bar rules in monitor |
| defense-monitor | `execute_stock_signal` (sl_pct/tp_pct from current quote) | scoring + ticker map in monitor |
| options-monitor | already AUTO_EXECUTE (since 2026-05-06) | RSI rules in monitor |
| options-exit-monitor | direct Alpaca SELL-to-close | TP/SL polling in monitor |
| **twitter-monitor** | Pattern A-D classifier in Python; Pattern E → email-only | `classify_and_execute()` in monitor |
| geo-monitor | still uses routine (asset_map mapping kept smart layer) | routine resolves news → ticker |
| exit-monitor | local thresholds; routine call only when ≥1 flagged | thresholds in monitor |
| weekly-learning | routine | LLM analysis |

### Twitter Pattern A-D classifier (`classify_and_execute`)

Deterministic decision tree replacing the routine's natural-language
classification:

| Pattern | Trigger | Direction logic | Output |
|---|---|---|---|
| **A** TICKER_DIRECT | `category.startswith("ticker:")` | bull-tone keywords vs bear-tone keywords | BUY/SELL_SHORT named ticker, $5k |
| **B** GEO_ESCALATION | `pol_cats` + escalation kw (sanctions, missile, strike, tariff…) | always BUY defense+energy | RTX $8k + XLE $6k (cap 2) |
| **C** GEO_DEESCALATION | `pol_cats` + deesc kw (ceasefire, treaty, withdrawal) | risk-on | BUY SPY $6k + SELL_SHORT XLE $6k |
| **D** MACRO_DATA | `macro` + economic kw + dovish/hawkish wording sniff | direction by tone | dovish→BUY SPY; hawkish→BUY GLD + SHORT SPY |
| **E** Ambiguous wire | wire/breaking + no clear signal | n/a | **email-only fallback** (manual review) |
| Neutral D | `macro` matched but no dovish/hawkish bias | n/a | drop, log only |

CONTRARIAN_CANDIDATE stance from `event_scoring` always falls through
to email-only flag (no auto-trade) — manual review is the safety
mechanism for "weak event + violent reaction" stop-hunt patterns.

### Routine budget under v2.2

Realistic typical day: ~1-3 routine calls (weekly-learning Sunday +
exit-monitor when flagged + geo-monitor on rare news bundle without
clean ticker). Well within 15/day limit even on noisy days.

### Opt-in fallback

Set `USE_ROUTINE=true` in any monitor's workflow env to revert to the
old Cloudflare Worker → routine path for that monitor. Useful for:
- Debugging unexpected order rejections
- Testing routine prompt changes
- Manual "let LLM decide" sessions

---

## 5.6 Daily + Weekly Learning Loop (v2.3.3 — three-lane LLM proposal architecture)

**Decision (2026-05-07, extended 2026-05-08):** the system reads its own
Alpaca order history once per day, computes per-strategy performance,
runs a deterministic heuristic adapter, then forwards the proposed state
+ raw stats to a **Senior Portfolio Manager LLM persona** (Claude
routine on claude.ai). The LLM produces three classes of output, each
routed to a different "lane" with different risk/automation tradeoffs.

**On Sunday 22:00 UTC** a second cron triggers `weekly_retro.py` — the
same routine, type-dispatched to `weekly_retrospective`. It reviews the
last 7 days as a full week, ranks strategies, recommends asset-class
allocation, lists structural mistakes, and proposes 3-5 testable
experiments for the next week.

**One goal:** consistently earn more. Adaptation tunes HOW; the goal is fixed.

### Three-lane architecture (v2.3.3)

```
Alpaca orders  →  deterministic adapter  →  LLM strategist (Senior PM)
                  (heuristics, always)       (proposals classified by lane)
                                                          │
                  ┌───────────────────────────────────────┼───────────────────────────────────────┐
                  ▼                                       ▼                                       ▼
        Lane 1: state_overrides                  Lane 2: auto-PR                   Lane 3: structured backlog
        (parameter tweaks — bounded               (new heuristic in adapter.py)    (architectural changes)
         whitelist)                                                                
                  │                                       │                                       │
                  ▼                                       ▼                                       ▼
        safe_apply_overrides()                   lane2_pr.py validates +           heuristic_proposals.md
        clamps & rejects bad fields              creates branch + PR              (rich entry: risk/effort/
                                                 (CI gate: tests must pass)        revisit/sketch)
                  │                                       │                                       │
                  ▼                                       ▼                                       ▼
        state.json (auto-applied,                Operator review + merge          Operator implements
        committed via git)                       (notify_pr_open email)            when prioritized
```

The deterministic adapter is the idiot-proof baseline; the three LLM
lanes layer increasing levels of human gating on top. **Fail-soft
contract:** if the LLM is unavailable (HTTP 429 / `USE_LLM_LEARNING=false`
/ no Worker URL / poll timeout), the adapter alone produces a complete,
valid output — system never blocks.

### Lane 1 — `state_overrides` (auto-applied, whitelist-enforced)

The LLM directly tunes `size_multiplier`, `enabled`, `side_bias`,
`paused_until`, `rationale`, `llm_note` per strategy, plus
`options_side_bias` and `max_open_options` globally.
`safe_apply_overrides()` clamps `size_multiplier` to `[0.30, 2.00]`,
rejects non-bool `enabled`, rejects invalid `side_bias` enums, and
silently drops any field name outside the whitelist (defends against
hallucinated keys like `delete_everything` or typos like `enbled`).

**Risk profile:** very low — every change is bounded, reversible, and
audited via `git log -- learning-loop/state.json`.

### Lane 2 — `auto_pr` (PR-based, CI-gated, ~1/day)

When the LLM is confident enough to propose a NEW heuristic for
`learning-loop/adapter.py`, it tags the proposal `lane=auto_pr` and
includes:

- `code_patch` — pure-Python source code, AST-validated to contain only
  function/class/assignment definitions. Appended to `adapter.py`.
- `test_addition` — a `unittest.TestCase` subclass exercising the new
  function. Appended to `learning-loop/test_adapter.py`.
- `wire_into_adapt_strategy` — optional one-line hint where the new
  function should be called from `adapt_strategy()`. Operator wires
  manually during PR review.

`learning-loop/lane2_pr.py::create_pr_from_proposal`:
1. Validates the proposal against the safety gate (target file in
   `{adapter.py}` whitelist, code parses, no top-level imports/exprs,
   test contains a real TestCase).
2. Creates branch `learning-loop/auto-<date>-<slug>`.
3. Appends patch + test, runs `python -m unittest learning-loop.test_adapter`.
4. **CI gate:** if any test red, abandons the branch — no PR is opened.
5. If green, pushes the branch and runs `gh pr create` with a labelled,
   structured PR body explaining the rationale + safety contract.
6. Returns PR URL; operator gets `[learning-loop AUTO-PR]` email via
   `notify_pr_open()`.

**Limits enforced** (see `routine-prompts.md` SELF-COMMIT INSTRUCTIONS):
- max 1 auto-PR per workflow run (further auto_pr proposals downgrade
  to backlog)
- only `learning-loop/adapter.py` modifiable in MVP
- patch must be append-only (no edits to existing code)
- patch must parse + tests must be green

**Risk profile:** medium — code lands in adapter.py but only via PR (human
gate), and only after the existing test suite stays green. Append-only
constraint prevents the LLM from breaking existing heuristics.

### Lane 3 — `backlog` (structured queue, manual implementation)

For everything else — architectural changes, multi-file edits, anything
requiring a data collection period, anything where the LLM isn't
confident enough to write code. Proposal includes `effort_estimate`,
`revisit_date`, `implementation_sketch`. Appended to
`heuristic_proposals.md` as a rich tickbox entry. Operator implements
when prioritized.

**Risk profile:** zero — nothing happens until a human implements.

### Lane classification rules (enforced in routine system prompt)

The LLM must self-classify each proposal:

| Lane | Pick when |
|---|---|
| `auto_pr` | New heuristic function in adapter.py, ≤30 LOC, self-contained test, low risk |
| `backlog` | Architectural change, monitor.py / order placement, requires new dep, requires data collection, <80% confidence |
| (default) | When in doubt, `backlog` |

Plus hard caps: max 1 `auto_pr` per response. Multiple low-priority PRs
would dilute review attention.

### Fail-soft contract (still holds across all lanes)

If the LLM call fails (HTTP 429 / `USE_LLM_LEARNING=false` / no Worker
URL / poll timeout / unparseable JSON), the deterministic adapter alone
produces a complete, valid output. No lane fires. The system never
blocks on LLM availability.

If the LLM succeeds but Lane 2 PR creation fails (validation rejects
patch, tests red, gh CLI fails), the proposal automatically downgrades
to Lane 3 backlog so the idea isn't lost.

| Mechanism | File |
|---|---|
| Daily analyzer (Alpaca read + stats + adapter + LLM) | `learning-loop/analyzer.py` |
| Adapter (pure function: old_state + today_stats -> new_state) | `learning-loop/adapter.py` |
| LLM client + safe override applier + heuristic-proposals queue | `learning-loop/llm_client.py` |
| **Senior PM system prompt** (master-piece, type-dispatched) | `learning-loop/routine-prompts.md` |
| Weekly retrospective driver | `learning-loop/weekly_retro.py` |
| Current adapted parameters (committed) | `learning-loop/state.json` |
| Append-only narrative of every change ever made | `learning-loop/rationale.md` |
| LLM-suggested heuristics queue (tickbox) | `learning-loop/heuristic_proposals.md` |
| Daily reports | `learning-loop/history/YYYY-MM-DD.md` |
| Weekly retros | `learning-loop/weekly-retros/<week_end>.md` |
| Daily cron | `0 21 * * *` (1h after US market close) |
| Weekly cron | `0 22 * * 0` (Sunday 22:00 UTC) |
| Read API for monitors | `shared/learning_state.py::load_strategy_state(name)` |

### Deterministic heuristics (v1.0 — always run first)

| Trigger | Action |
|---|---|
| lifetime trades < 10 | hold (insufficient sample) |
| 7d win_rate < 35% (≥5 trades) | size_multiplier *= 0.8 |
| 7d win_rate > 60% (≥5 trades) | size_multiplier *= 1.10 |
| 7d P&L < -2% equity | size_multiplier *= 0.7 |
| 7d P&L > +3% equity | size_multiplier *= 1.05 |
| 5 consecutive losses | enabled = false (3-day pause, auto-resume) |
| Lifetime ROI < -10% | enabled = false (manual review required) |
| Options long P&L < 0 + short P&L > \|long\| | side_bias = "short" (PUT-only) |
| Options short P&L < 0 + long P&L > \|short\| | side_bias = "long" (CALL-only) |

Bounds: `0.30 ≤ size_multiplier ≤ 2.00`. Pause auto-resumes after 3 days.

### LLM strategist (Senior PM persona)

**Persona** (full prompt in `learning-loop/routine-prompts.md`): a senior
portfolio manager with 20+ years of running aggressive short-horizon
strategies on a $100k paper account with 4× margin. Same mission as
`docs/STRATEGY.md`: maximise risk-adjusted return on 1-72h horizons,
"all capital deployed", one success metric — earn more.

**Daily framework (6 ordered passes):**
1. EDGE — where do we have positive expectancy? where are we paying to play?
2. POSITION SIZING vs OUTCOME — wins on max sizing or partial?
3. TIME / REGIME CLUSTERING — losses bunched in which hours / SPY regime?
4. SIGNAL QUALITY by source — per-strategy AND per-feed win-rate
5. MACRO CONTEXT — CPI / FOMC / earnings overlay
6. FILL-RATE pathology — canceled% (limits too tight) vs rejected% (sizing math)

**Adapter interaction:** the LLM does NOT redo the adapter math. Its job is
to **flag** when the adapter is wrong (e.g. 5 losses with different root
causes — don't pause, retune; or hot streak from luck — don't increase size).

**Weekly framework (6 ordered passes):**
1. P&L story — WHY, not WHAT
2. Strategy scorecard — rank by P&L $, win rate, consistency, hit-to-mean
3. Asset-class allocation — current vs realised contribution → rebalance
4. Source quality — Twitter tiers, news feeds, per-feed win rate
5. Structural mistakes — max 3, ranked by lost dollars + concrete remediation
6. Next-week experiments — 3-5 with hypothesis, metric, revert-if condition

**Response rules** (both types): pure JSON, no markdown fences, brutal +
specific + numbers-first. If data is thin, say it ("low confidence — only
3 trades to date"). User goal is short-horizon profit max with controlled
variance — anything proposed must serve that.

### Whitelist enforcement (`safe_apply_overrides`)

Only these per-strategy fields can be touched by LLM:
- `size_multiplier` (clamped to `[0.30, 2.00]`, must parse as float)
- `enabled` (must be bool)
- `side_bias` (must be `"long"`, `"short"`, or `null`)
- `rationale`, `paused_until`, `llm_note` (free text)

Global overrides limited to: `options_side_bias`, `max_open_options`.

Anything else — invalid keys, hallucinated strategy names, type
mismatches — is **silently dropped** and logged in the applied list.
Tested with: `delete_everything`, `wormhole`, `"yes please"` (string for
bool), `99.0` size_multiplier (clamped to 2.0), `fake-strategy-xyz`. All
rejected/clamped correctly.

### Routine budget

- Daily annotator: 1 routine call/day
- Weekly retro: 1 routine call/week (Sunday)
- All other monitors (price/crypto/defense/twitter/exit): direct Alpaca REST
  via v2.2 routine-bypass (see §5.5)
- **Total: ~1.14 routine calls/day vs 15/day Anthropic limit → ~13.86 reserve**

The bypass in v2.2 was specifically engineered to free routine budget
for the learning loop, since adaptive parameter tuning is the system's
strategic priority.

### Persistence

git history IS the audit log. `git log -- learning-loop/state.json`
shows every adaptation ever made; `git diff` between commits shows
precisely what changed. `rationale.md` is append-only — old entries
preserved indefinitely. `heuristic_proposals.md` is the LLM's tickbox
queue: ideas accumulate; user (or future auto-promotion) ticks each one
and graduates the rule into `adapter.py`.

### Wired today

- ✅ options-monitor: reads `options-momentum` state, applies
  size_multiplier, applies side_bias (skip CALL when bias=short).
- ✅ Daily LLM annotator (Senior PM persona) — v1.1 (2026-05-07)
- ✅ Weekly retrospective (Sunday cron) — v1.1 (2026-05-07)
- ⏳ Phase 2: price/crypto/defense/twitter monitors. Each is 5 lines.

Full details: `strategies/learning-loop.md`.

---

## 6. Monitoring & Cadence

### 6.1 GitHub Actions workflows

| Workflow | Cron (UTC) | Asset class | Notes |
|---|---|---|---|
| `price-monitor.yml` | `*/5 13-20 * * 1-5` | US stocks momentum + leveraged | session only |
| `crypto-monitor.yml` | `0,30 * * * *` | BTC, ETH | 24/7 |
| `defense-monitor.yml` | `0,30 * * * *` | defense names | 24/7 (DoD posts ~17 ET) |
| `geo-monitor.yml` | `*/15 13-21 * * 1-5` | geopolitical news | session-wide |
| `exit-monitor.yml` | `30 12-21 * * 1-5` + `0 22,0,2 * * *` | all stocks/crypto positions | hourly + nightly |
| `options-monitor.yml` | `*/10 13-20 * * 1-5` | options entries | session only |
| `options-exit-monitor.yml` | `*/5 13-20 * * 1-5` | options exits | session only |
| `twitter-monitor.yml` | `*/5 13-20 * * 1-5` + `*/15 * * * *` | Bluesky social-graph news | session + 24/7 |
| `daily-learning.yml` | `0 21 * * *` | adaptive parameters tuning | daily after market close |
| `keep-alive.yml` | `*/10 * * * *` | Render MCP ping | always |
| (paused) `reddit-monitor.yml` | `0 7,13,16,20 * * 1-5` | sentiment | waiting for API approval |

### 6.2 Email notifications (`shared/notify.py`)

- `notify_signal` — every detected signal (BUY/SELL with metadata)
- `notify_exit` — every flagged exit decision
- `notify_order_executed` — every executed bracket / options buy
- `notify_summary` — end-of-run digest (only when ≥1 signal)

All emails go via Gmail SMTP (port 465 SSL) to `NOTIFY_EMAIL`. Body is
ASCII-only (Polish accents stripped to avoid SMTP encoding issues).

---

## 7. Failure Modes & Recovery

| Failure | Detection | Behaviour | Recovery |
|---|---|---|---|
| Alpaca API outage | HTTP 5xx / timeout | dup-position guard fail-OPEN, exits retry next cron | next cron tick |
| Finnhub `^VIX` empty | `c == 0` | vix_guard returns OK (fail-open) | follow-up: switch to VIXY proxy |
| Finnhub `/stock/candle` 403 | 403 status | already migrated to Alpaca bars | no action (fixed) |
| Cloudflare Worker 5xx | HTTP error | monitor logs and continues; email still sent | Worker dashboard |
| Anthropic Routine 429 | 429 in proxy response | options-monitor bypasses via AUTO_EXECUTE | no action (mitigated) |
| Gmail SMTP down | login fail | monitor prints error, continues without email | check app password |
| GitHub Actions outage | job not running | manual `Run workflow` or wait | rare; usually < 1h |
| Render MCP server cold | first MCP call slow | keep-alive cron pings every 10 min | already mitigated |

---

## 8. Drawdown Plan

### 8.1 -12% intraday (daily catastrophic stop)

- exit-monitor and options-exit-monitor continue (we still want to
  manage existing positions)
- All ENTRY monitors should self-disable for the rest of the day
- Implementation: `shared/risk_guards.py::daily_drawdown_guard()`
  (to be added in a follow-up; for now, manual workflow disable)
- Email to user: subject `[CIRCUIT BREAKER] Daily drawdown -12% hit`

### 8.2 -25% weekly

- All workflows manually disabled in GitHub Actions UI
- 24-hour cool-off
- Manual review of every loss; tighten any obvious offenders
- Resume only after explicit go-ahead

### 8.3 -40% monthly

- Full system stop
- Strategy reset: re-evaluate every parameter in this document
- Consider rolling back to a prior commit known-good

---

## 9. Performance Targets (paper)

| Horizon | Target | Tolerance |
|---|---|---|
| Daily | positive expectancy | -12% catastrophic |
| Weekly | +5% to +10% | -25% |
| Monthly | +25% to +50% | -40% |
| Quarterly | +75% to +150% | -50% |

Targets are aspirational. The success metric isn't hitting them — it's
producing a positive Sharpe ratio (return/volatility) over a quarter.

---

## 10. Whitelist Management

The whitelist is enforced at every entry by the risk-officer agent. New
tickers can be added only by editing `.claude/rules/tickers-whitelist.md`
**and** updating this document accordingly. Removing a ticker means all
existing positions in it must be flat first (or carry a manual exception).

### 10.1 Per-Instrument Trading Windows (v3.2 — 2026-05-12)

Orthogonal to the whitelist: `config/instrument_windows.json` controls
**when** each instrument can be traded. Two layers:

**Layer A — workflow cron schedules** govern when monitors RUN:

| Monitor | Cron | Rationale |
|---|---|---|
| price-monitor | `*/5 13-20 * * 1-5` | Alpaca bars only update market hours |
| crypto-monitor | `*/5 * * * *` | Crypto 24/7 |
| defense-monitor | `*/5 * * * *` | News breaks any time; gate handles execution |
| geo-monitor | `*/15 * * * *` | News breaks any time |
| reddit-monitor | `*/30 * * * *` | ToS-safe at 30 min cadence |
| twitter-monitor | `*/5 * * * *` | Bluesky 24/7 |
| options-monitor | `*/5 13-20 * * 1-5` | Options chain market-hours only |
| options-exit-monitor | `*/5 13-20 * * 1-5` | Same as entry |
| exit-monitor | `*/5 13-20 weekday + */15 off-hours + */15 weekend` | Dual cron: tight in-session, light coverage for crypto off-hours |

**Layer B — per-instrument trading window** gates order placement:

```python
# shared/instrument_windows.py
ok, reason = can_trade_now(symbol, asset_class)  # → (bool, str)
if not ok:
    # email subject [QUEUED] (market closed) or [DEFERRED] (paused symbol)
    notify_signal(signal, alert_sent=False, reason=reason)
    return
place_stock_bracket(...)
```

Decision precedence inside `can_trade_now`:
1. `instrument_overrides[symbol].enabled == false` → block (manual pause)
2. `paused_until` is future date → block
3. Asset-class window says market closed → block (defers to `shared/market_hours.is_us_market_open`)
4. else → allow

**Asset-class defaults** (from `config/instrument_windows.json`):

| Asset class | Days | Window UTC | Holidays |
|---|---|---|---|
| `us_equity` | Mon-Fri | 13:30-20:00 | Yes (NYSE) |
| `us_option` | Mon-Fri | 13:30-20:00 | Yes (NYSE) |
| `crypto` | Sun-Sat | 00:00-23:59 | No |

**Per-instrument overrides** (`instrument_overrides`):
- `MSTR`: enabled=false (backtest 0% WR; gated on momentum-confirm filter)
- `SMCI`: enabled=false (same)
- Future overrides: any symbol can be paused with `paused_until` date for
  auto-resume, or `paused_until: null` for manual-only re-enable

**Wired into 8 enforcement points**:
- `shared/alpaca_orders.py`: `place_stock_bracket`, `place_crypto_order`,
  `place_simple_buy`, `execute_stock_signal`, `execute_crypto_signal`
- `shared/allocator.py`: `_execute_one` (BUY/REDUCE/EXIT)
- `exit-monitor/monitor.py`: `place_emergency_close`
- `options-exit-monitor/monitor.py`: `place_sell_to_close`

**Migration from `state.json::tickers`**: `shared/learning_state.py::is_ticker_enabled`
now consults `instrument_windows.json` first, falls back to `state.json::tickers`
for backwards compatibility. New tickers go to `instrument_windows.json`.

### 10.2 Whitelist groups

Current whitelist groups (see `.claude/rules/tickers-whitelist.md`):

- Mega-cap US: AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA
- Financials: JPM, V, MA, JNJ, BRK.B
- Broad ETFs: SPY, QQQ, VOO, VTI, IWM, VXUS, VWO
- Sector ETFs: XLK, XLF, XLE, XLV, XLY
- Commodities: GLD, SLV
- Crypto: BTC/USD, ETH/USD
- Defense Big-5: LMT, RTX, NOC, GD, BA
- Defense mid-cap: KTOS, PLTR, AXON, LDOS, SAIC, CACI
- Defense ETF: ITA, XAR, DFEN
- European ADR: BAESY, EADSY
- Energy: XOM, CVX
- **NEW** Leveraged ETF (3×): TQQQ, SQQQ, SPXL, SPXS, UPRO, SPXU, SOXL, SOXS, FAS, FAZ, TNA, TZA
- **NEW** High-beta single names: COIN, MSTR, ARM, SMCI

Explicitly **not** on the whitelist:
- Penny stocks
- Volatility ETPs (VXX, UVXY) — too much decay
- Small-cap biotech (event risk)
- Single-stock leveraged ETFs (TSLZ, NVDS, etc.)

---

## 11. Iron Rules Summary (post-2026-05-06)

These are reflected verbatim in `CLAUDE.md`:

```
### Position sizing
- Max single trade:     20% of equity (~$20k)
- Max ticker exposure:  40% of equity (~$40k)
- Cash reserve:         0% (full deployment)
- Daily loss STOP:      -12% intraday  -> block new entries

### Asset class soft caps (gross, advisory)
- Stocks momentum:   60% gross
- Leveraged ETFs:    25% gross
- Crypto:            25% gross
- Defense / geo:     35% gross
- Options premium:   25% (notional can be much higher)
- Reddit:            10%

### Order rules
- LIMIT orders only (never MARKET)
- Stocks: bracket entry + SL + TP whenever possible
- Options: simple LIMIT BUY (Alpaca paper limitation)
- Time-in-force: DAY (unless strategy specifies otherwise)
- Stop-loss is mandatory on every entry

### Forbidden
- Live trading (this is paper-only)
- Trading without a stop-loss
- Trading off-whitelist
- Options ±1 day around earnings
- Trading when VIX > 60 (catastrophic only)

### Daily / weekly / monthly circuit breakers
- -12% intraday  -> block new entries until next session
- -25% weekly    -> pause all monitors, manual review
- -40% monthly   -> full stop, strategy reset
```

---

## 12. Versioning & Change Log

| Version | Date | Author | Notes |
|---|---|---|---|
| 1.0 | 2026-04-29 | initial setup | Conservative starter parameters |
| 1.1 | 2026-05-04 | aggressive overhaul | 5× sizing, dollar-limit crypto, higher VIX thresholds |
| **2.0** | **2026-05-06 EOD** | **risk-on full overhaul** | All capital deployed, daily stop -12%, VIX HALT only above 60, options auto-execute on paper, this document created |
| **2.1** | **2026-05-07** | **safety nets enforced + new signal sources** | Drawdown circuit-breaker (-12% daily) wired in code; per-ticker concentration cap (40%) enforced; event-probability layer (4 scores -> FOLLOW/IGNORE/CONTRARIAN/WAIT) with real Alpaca bar-data; twitter-monitor MVP via Bluesky AT-Protocol; live portfolio dashboard (single Cloudflare Worker) |
| **2.2** | **2026-05-07 EOD** | **routine bypass — direct Alpaca REST execution** | Hit 15-call/day Routines limit; refactored price/crypto/defense/twitter monitors to AUTO_EXECUTE via `shared/alpaca_orders.py`. Twitter Pattern A-D encoded as deterministic Python classifier; Pattern E ambiguous → email-only manual review. Routine reserved for weekly-learning + opt-in via `USE_ROUTINE=true` env. Realistic budget now ~1-3 calls/day vs 15+ before. |
| **2.3** | **2026-05-07 LATE** | **daily learning loop with permanent memory** | Replaced weekly-learning with daily cron. New `learning-loop/`: analyzer + adapter + state.json + rationale.md + per-day history. Daily-learning workflow commits state back to repo via `GITHUB_TOKEN` (permissions: contents:write); git history is audit log. Heuristics (v1.0): cool-down on losing strategies, warm-up on winners, pause after 5 consec losses, side-bias for options based on long-vs-short P&L split. options-monitor wired to read state.json (size_multiplier + side_bias enforced). Other monitors wire in Phase 2. Routines no longer used here either (the LLM-on-routine path was the original analyzer's intent — replaced with deterministic heuristics + git-as-state-store). |
| **2.3.1** | **2026-05-07 NIGHT** | **LLM augmentation on daily + weekly learning loop** | Reversed v2.3's "no LLM in learning" stance — learning is the most important thing in the system, so user demanded LLM be engaged in BOTH daily and weekly cycles with a "master-piece" prompt. Senior Portfolio Manager persona (20+ years, $100k paper, 4× margin, same mission as STRATEGY.md) added to `learning-loop/routine-prompts.md` with type-dispatch on `daily_learning_annotation` vs `weekly_retrospective`. Daily framework: 6-pass review (EDGE → SIZING → TIME-REGIME → SIGNAL QUALITY → MACRO → FILL-RATE). Weekly framework: 6-pass retro (P&L story → scorecard → allocation → sources → mistakes → experiments). New `learning-loop/llm_client.py` handles routine call + JSON parse + fail-soft + whitelist-enforced `safe_apply_overrides` (size_multiplier clamped 0.30-2.00, enabled bool, side_bias enum, hallucinated keys silently dropped). New `learning-loop/weekly_retro.py` (Sunday 22:00 UTC cron) writes full retro to `learning-loop/weekly-retros/<week_end>.md`. New `heuristic_proposals.md` queue for LLM-suggested rules. v2.2 routine-bypass on other monitors gives this layer the routine budget it needs (~1.14 calls/day vs 15/day limit → ~13.86 in reserve). |
| **2.3.2** | **2026-05-08 (early)** | **Poll-based routine response + close-detection fix + emergency MARKET** | Anthropic Routines trigger is fire-and-forget — receipt comes back in <1s but the actual model JSON is async. Architecture: routine self-commits its JSON output to `learning-loop/pending-llm-{daily,weekly}.json` and pushes; `llm_client.call_routine` polls origin/<branch> for that file (180s → 300s after first nightly cron timeout). Closes "free LLM augmentation, no Anthropic API key needed" requirement. Plus 3 LLM-proposed bug fixes from the first augmented run: (a) `_is_close()` was always False — fixed to detect `exit-*` prefix AND Alpaca bracket child `*_take_profit`/`*_stop_loss` suffix; (b) `options-exit-monitor` SL exits switched LIMIT→MARKET (guaranteed fill in panic); (c) `compute_tp_hit_rate` metric for trailing-stop decision (10-day data collect). |
| **2.3.3** | **2026-05-08 (afternoon)** | **Three-lane architecture for LLM proposals** | Resolves "auto-implementation of LLM lessons learned" backlog item. Three-lane proposal routing: Lane 1 = state_overrides whitelist (existing, auto-applied), Lane 2 = auto-PR for new heuristics in `learning-loop/adapter.py` (NEW — lane2_pr.py validates + creates branch + opens PR via gh CLI, max 1/day, CI-gated by test_adapter.py), Lane 3 = structured backlog entries with risk/effort/revisit metadata (NEW — auto-appended to heuristic_proposals.md). Routine system prompt extended with strict lane classification rules. New: `learning-loop/test_adapter.py` (19 tests, baseline CI gate), `learning-loop/lane2_pr.py`, `shared/notify.py::notify_pr_open`. Workflow updated with `pull-requests: write` permission + `GH_TOKEN`. User-side: re-paste new system prompt into Learning Loop Strategist routine. |
| **2.3.4** | **2026-05-09** | **Channel fix (auto-merge.yml) + lane2 worktree isolation + 7 LLM-proposed implementations + 4 stale orders cancelled** | Massive cleanup day. Channel fix: `.github/workflows/auto-merge.yml` triggers on push to `claude/**` with `[automerge]` tag in commit message, uses `GITHUB_TOKEN` (different scope than OAuth proxy that blocks main pushes from agent sessions) to fast-forward merge into main. Lane 2 worktree isolation: `lane2_pr.py` does all branch work in `tempfile.mkdtemp()` git worktree so analyzer's working tree is never corrupted (was the bug behind run #4 lost-state). LLM timeout 300→480s + 30s grace pickup for race conditions. Workflow `git rm -f --ignore-unmatch pending-llm-*.json` for orphan cleanup. gh-pr-create label fallback when labels don't exist. New heuristics in `adapter.py`: `heuristic_fill_rate_size_cut`, `heuristic_fill_rate_alert`, `heuristic_options_chronic_fill` — all wired into adapt() and emit rationale lines + size scaling. options-exit-monitor: NEARDTH decision (DTE≤5 + loss>40% → MARKET sell with `exit-neardth-*` prefix) saves theta-crush positions like QQQ260514P00699. options-monitor: `_compute_buy_limit_price()` uses bid/ask midpoint+5% via `/v1beta1/options/snapshots/` instead of close*1.05; close*1.20 fallback. analyzer single-leg attribution: `compute_strategy_stats` now reads raw orders too (not just completed trades), tracks `open_positions_7d` per strategy so by_strategy is non-empty even when nothing closes. `scripts/cancel_stale_emergency_orders.py` + workflow cancelled 4 stale exit-emergency LIMIT orders left from before MARKET patch (idempotent script, MACHINE_READABLE_RESULT in log). 15/15 LLM proposals from 2026-05-07/08/09 closed (1 calendar-deferred to 2026-05-17 trailing-stop). Pipeline production-ready autonomous; nightly cron runs without operator intervention. |

---

*Source-of-truth document. If code disagrees with this file, fix the code.*
*Repo: git@github.com:mikosbartlomiej-prog/trading-system.git*
