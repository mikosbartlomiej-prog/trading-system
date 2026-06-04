# Feedback Requirements Analysis

**Source:** Trader feedback received 2026-06-03 (transcribed in prompt 2026-06-04).
**Reviewer:** principal-engineer + audit cycle 2026-06-04.
**Status:** v1.0 — initial mapping after repo audit.

> **Operating constraint (hard rule):** system MUST stay free to operate.
> No paid APIs, paid DBs, paid cloud monitoring, paid alerting, paid data.
> Allowed: local files, SQLite, DuckDB, CSV/Parquet/JSONL, open-source,
> free legal public data. No promises of profits. Risk engine final word.

---

## Mapping table

| ID | Feedback (paraphrased) | System interpretation | Priority | Exists in repo? | Evidence | Recommendation |
|---|---|---|---|---|---|---|
| **FB-001** | Profile a stock — how it behaves | `InstrumentProfile` deterministic model: per-symbol behavior stats (volatility, intraday range, gap behavior, RSI distribution, volume ratio, drawdown stats) computed from local bars | **P0** | **NO** | grep returns 0 matches for `instrument_profile`, `symbol_profile`, `TickerBehavior` | Build new `shared/instrument_profile.py`; deterministic computation from `market_data.get_daily_bars`; cache locally; feed confidence score |
| **FB-002** | Pre-open behavior predicts opening behavior | `PreOpenBehaviorModel` — gap %, gap direction, pre-market volume (if data), distance from prev close → classify open behavior (gap-and-go / gap-fill / open-drive / open-rejection / mean-reversion / chop / delayed-continuation / false-breakout) | **P1** | **PARTIAL** — `market_hours.py` knows what "pre_market" means but no analysis | grep finds only window classification | Build `shared/pre_open_behavior.py` — interface + synthetic data tests. Real pre-market bars require Alpaca SIP feed (paid) → use IEX feed only for first-minute bars after open. Document data limitation. |
| **FB-003** | Index/sector pulls a stock | `LeadLagAnalyzer` — rolling correlation vs SPY/QQQ/sector ETF + lead-lag detection (does the stock follow with delay?) | **P1** | **NO** | grep returns 0 matches | Build `shared/lead_lag_analyzer.py`. Use existing `market_data.get_daily_bars` for SPY/QQQ + symbol. Compute Pearson + lagged correlation. |
| **FB-004** | Dynamic profile for selected stock | `DynamicInstrumentProfiler` — on-demand profile when monitor selects a ticker (existing or new); profile carries `quality_score` (sample size + freshness) | **P0** | **NO** | n/a | Build alongside FB-001. Output `InstrumentProfile` with `quality` field. Insufficient data → quality=0 → confidence-conservative. |
| **FB-005** | All strategies must be backtested | Each enabled strategy in `state.json` MUST have a backtest path | **P0** | **PARTIAL** — `backtest/run.py` exists but only `SIGNALS` registry has 3 strategies (momentum-long / momentum-long-loose / overbought-short). 9 enabled strategies in state.json. | `grep "SIGNALS" backtest/run.py` shows 3 entries; `state.json::strategies` has 12 | Register remaining strategies (crypto-momentum / crypto-oversold-bounce / geo-defense / geo-energy / geo-gold / geo-xom / options-momentum / allocator-rebalance) via `StrategyRegistry` shim. Some are event-driven and need different harness (replay vs walk-forward). Document gap honestly. |
| **FB-006** | Source quality policy | Formal `SourceQualityPolicy` — Tier 1 (primary/official) / Tier 2 (verified/curated) / Tier 3 (social/secondary) | **P0** | **PARTIAL** — `event_scoring.py` has `source_type` + `cred` numbers but no formal Tier 1/2/3 contract or test | `shared/event_scoring.py` lines ~20-60 | Build `shared/source_quality.py` with explicit Tier enum + classification helper + tests. Wire into news monitors. |
| **FB-007** | Primary-source event monitors needed | Defense (free DoD/RSS) + politician (free SEC EDGAR / House Clerk) already exist. Need DOJ + legal/lawsuit monitor for company-specific catalyst. | **P2** | **PARTIAL** — defense-monitor + politician-monitor live; no DOJ/legal | `defense-monitor/`, `politician-monitor/` directories | Design interface `shared/event_monitor_interface.py` + mocks + tests; do NOT add new live monitor (no time + no validated free data source yet — DOJ press releases are RSS but parsing is brittle). Document as future work. |
| **FB-008** | DOJ / legal proceedings monitor | New monitor for company lawsuits, regulatory actions | **P2** | **NO** | n/a | Defer to interface design (alongside FB-007). Free source candidates: SEC EDGAR 8-K filings (Item 1.01 legal proceedings), DOJ press releases RSS, PACER court records (no free API). Document feasibility. |
| **FB-009** | Defense monitor good (primary source) | Already exists | n/a | **YES** | `defense-monitor/monitor.py` | Confirm + verify source_tier=1 attribution in code. |
| **FB-010** | US vs microcaps vs PL — universe choice | `MarketUniverseConfig` — multiple universes (US_LARGE / US_MICROCAP / PL) with per-universe data/risk/slippage assumptions | **P2** | **PARTIAL** — bucket-organized US universe only | `config/watchlists.json` only US tickers | Build `config/market_universes.json` + `shared/universe_selector.py`. PL data via free GPW open data is feasible but no Alpaca integration → operator decision (out-of-scope for paper trading). Document limitations. |
| **FB-011** | Position management (fire-and-forget bad) | `PositionManager` / `TradeLifecycleManager` — explicit lifecycle (ENTRY → MONITORING → PARTIAL_EXIT → FULL_EXIT) with invalidation, time-stop, MAE/MFE, trailing, exit-on-confidence-drop | **P0** | **PARTIAL** — exit-monitor + intraday_governor + safe_close handle reactive exits. No lifecycle state machine | `exit-monitor/monitor.py`, `shared/intraday_governor.py` | Build `shared/position_manager.py` — state machine that aggregates existing exits + adds invalidation + time-stop + confidence-drop exit. Stores per-position state in `runtime_state.json::positions`. |
| **FB-012** | Liquidity sweep / trap defense | `LiquiditySweepGuard` — detects long-wick reversals, volume spike no-follow-through, fast reversal post-breakout, low-liquidity entries | **P0** | **NO** | grep returns 0 matches | Build `shared/liquidity_sweep_guard.py`. Conservative: lower confidence + flag setup. NEVER generate trades; never raise aggressiveness. |
| **FB-013** | Real-time effectiveness verification | `SessionEffectivenessMonitor` — during-session metrics: signal count, rejection rate, hit rate (if computable), MAE/MFE, slippage proxy, confidence calibration | **P1** | **PARTIAL** — `scripts/session_report.py` is post-session. No in-session effectiveness | `scripts/session_report.py` | Build `shared/session_effectiveness.py` — append-only JSONL `learning-loop/session_metrics/<date>.jsonl`. Can trigger safe_mode if effectiveness drops below threshold. |
| **FB-014** | Social media de-prioritization | Reddit/Twitter classified Tier 3 — cannot raise confidence alone | **P1** | **PARTIAL** — Curator agents validate signals but no hard rule in confidence | `reddit-monitor/llm_curator.py`, `twitter-monitor/monitor.py` | Wire into `SourceQualityPolicy` (FB-006). Tier 3 alone caps confidence ≤ ALERT_ONLY threshold (no BLOCK promotion). |
| **FB-015** | DD as context not day-trading trigger | DD from verified authors = Tier 2 BUT catalyst timing unknown → not auto-day-trade trigger | **P2** | **PARTIAL** — `reddit-users.md` whitelist empty; Curator decides per-signal | `.claude/rules/reddit-users.md` | Document in `source_quality_policy.md`. Cap day-trade-suggested confidence from Tier 2 DD unless price/volume confirmation present. |

---

## Risk classification of feedback

| FB ID | Risk class | Rationale |
|---|---|---|
| FB-001, FB-004 | **Safe to implement** | Deterministic computation from local data. No live execution risk. |
| FB-002 | **Implement interface + tests only** | Real pre-market data costs money. Document limitation. |
| FB-003 | **Safe** | Pearson correlation over local data. Output advisory only. |
| FB-005 | **Safe** | Backtest is pure-historical. Document strategy coverage gaps. |
| FB-006, FB-014, FB-015 | **Safe** | Classification rule. Lowers confidence ceiling for Tier 3. Conservative direction. |
| FB-007, FB-008 | **Interface only** | New live monitors need source validation. Defer to user decision. |
| FB-009 | **Already done** | Verification step only. |
| FB-010 | **Design + interface; no migration** | US → PL/microcap requires data + broker validation. NOT in scope. |
| FB-011 | **Safe** | Aggregates existing exits + adds tighter exit-on-drop. Conservative direction. |
| FB-012 | **Safe** | Lowers confidence + blocks risky setups. Conservative direction. |
| FB-013 | **Safe** | Read-only metrics + optional safe_mode trigger. |

---

## Priorities for v3.15.0 implementation (this iteration)

**P0 (must ship):**
- FB-001 + FB-004: `shared/instrument_profile.py` + `DynamicInstrumentProfiler`
- FB-006: `shared/source_quality.py`
- FB-011: `shared/position_manager.py`
- FB-012: `shared/liquidity_sweep_guard.py`

**P1 (ship if time, else interface):**
- FB-003: `shared/lead_lag_analyzer.py`
- FB-013: `shared/session_effectiveness.py`
- FB-014: wire Tier 3 cap into confidence

**P2 (interface + docs only):**
- FB-002: `shared/pre_open_behavior.py` interface
- FB-007, FB-008: event monitor interface
- FB-010: `config/market_universes.json` + selector
- FB-005: register more strategies in `SIGNALS`
- FB-015: doc rule

---

## Hard constraints applied to ALL new modules

1. **Fail-soft:** any error → return None/empty; never raise to caller; log only.
2. **Deterministic:** same inputs → same output; no randomness; no clock-based behavior.
3. **Audit-able:** every decision affecting trades emits JSONL event.
4. **Conservative:** new signals can only LOWER confidence or BLOCK trade. Cannot raise aggressiveness or override risk engine.
5. **Risk-engine-last:** `shared/risk_officer.evaluate_trade` keeps final say.
6. **Free:** no paid services, no new dependencies that require accounts.
7. **Testable:** every public API has unit test before wiring.
