# Heuristic Proposals (LLM-generated)

> Open queue of heuristic ideas suggested by the daily LLM
> annotator + weekly retrospective. Tick the box `[x]` when
> implemented in `learning-loop/adapter.py`. Older entries
> kept indefinitely so we can audit which ideas worked.

- [x] [2026-05-07] Emergency exit orders (exit-emergency-*) muszą używać MARKET order ✅ DONE — exit-monitor.place_emergency_close + options-exit-monitor SL→MARKET (commits c4bc437, 0f7ce0b)
- [ ] [2026-05-07] TP orders niefilled przez całą sesję (exit-tp-qqq699) — rozważ trailing stop dla pozycji >12h. **DEFERRED** to ~2026-05-17 (10-day TP-hit-rate data collection).
- [x] [2026-05-07] analyzer.py musi mapować client_order_id do nazwy strategii ✅ DONE — _is_close + bracket-child detection (c4bc437, 8fcba17) + single-leg attribution (commit this batch)

<!-- ============================================================ -->
<!-- 2026-05-08 daily LLM output (rescued manually — routine push  -->
<!-- to main was blocked 403 by proxy; rescued from feature branch -->
<!-- claude/adoring-maxwell-YLZLC and applied here). Architectural -->
<!-- channel fix tracked separately in CLAUDE.md backlog.          -->
<!-- ============================================================ -->

- [x] [2026-05-08] **exit-emergency 0/4 filled** ✅ DONE (same as 2026-05-07 #1; commits c4bc437 + 0f7ce0b)
- [x] [2026-05-08] **options fill rate cap (heuristic_options_limit_too_tight)** ✅ DONE — Lane 2 PR #2 merged 2026-05-09; alert function lives in adapter.py
- [x] [2026-05-08] **analyzer single-leg attribution** ✅ DONE — `compute_strategy_stats` now tracks open_positions_7d per strategy from raw orders; by_strategy non-empty even when nothing closes
- [x] [2026-05-09] **Detect high-cancel-rate (heuristic_fill_rate_size_cut)** ✅ DONE — adapter.py + wired into adapt()
- [x] [2026-05-09] **Detect chronic options-momentum fill deficit** ✅ DONE — `heuristic_options_chronic_fill` in adapter.py + wired
- [x] [2026-05-09] **options-exit near-expiry accelerated close (DTE≤5 + loss>40%)** ✅ DONE — `_occ_dte` + NEARDTH branch in evaluate(); fires MARKET sell with `exit-neardth-` prefix
- [x] [2026-05-09] **options-monitor midpoint-based limit pricing (close*1.05 → midpoint*1.05)** ✅ DONE — `_get_option_quote` + `_compute_buy_limit_price` in options-monitor; bid/ask snapshot with close*1.20 fallback
- [x] [2026-05-09] **Alert on strategies with fill rate < 50%** ✅ DONE — `heuristic_fill_rate_alert` in adapter.py + wired
- [x] [2026-05-09] **Widen options-monitor limit (bid*1.05 → midpoint*1.15)** ✅ DONE — superseded by midpoint+5% implementation above (same fix, different threshold)
- [x] [2026-05-09] **Widen options entry limit by 8% above close_price (close*1.08)** ✅ DONE — superseded by midpoint*1.05 / close*1.20 fallback (more aggressive than 8%, same goal)
- [x] [2026-05-09] **Tag options-exit SELL_TO_CLOSE with client_order_id** ✅ DONE — already implemented as `_exit_client_order_id` in options-exit-monitor (commits c4bc437 + 0f7ce0b); analyzer's `_is_close` recognises `exit-tp-*` / `exit-sl-*` / `exit-neardth-*` prefixes

<!-- ============================================================ -->
<!-- OPEN — proposals still requiring action                      -->
<!-- ============================================================ -->

- [x] [2026-05-09] **Cancel pre-patch exit-emergency LIMIT orders stuck open in Alpaca** ✅ DONE 2026-05-09 — `scripts/cancel_stale_emergency_orders.py` + `.github/workflows/cancel-stale-emergency-orders.yml`; user ran workflow, **4/4 stale LIMIT orders cancelled** (GOOGL260515P00400, QQQ260515P00709, QQQ260514P00699, AMZN260513P00275). Script idempotent — safe to re-run.

<!-- ============================================================ -->
<!-- 2026-05-09 (rescued from commit 2beb4b7 — Senior PM output    -->
<!-- from timeout run, written to old path before routine prompt   -->
<!-- was updated; workflow cleanup removed file before route_      -->
<!-- proposals could process it. Manually appended here as Lane 3. -->
<!-- ============================================================ -->

- [ ] [2026-05-09] **Regime mismatch exit: proactive PUT close when side_bias=long + SPY uptrend** _(risk: medium, effort: 2-3h, revisit: 2026-05-14)_
  - **Rationale:** Gdy LLM ustawia `options_side_bias=long` w risk_on rally, stare PUT pozycje krwawią bez mechanizmu proaktywnego zamknięcia. Statyczny SL=entry*0.50 to za daleko — tracimy więcej niż konieczne zanim SL się aktywuje. Potrzebny dodatkowy trigger: jeśli `side_bias='long' AND pozycja jest PUT AND strata > -15% AND SPY 5d return > +1.5%`, zamknąć po midpoint niezależnie od SL.
  - **Sketch:**
    1. `options-exit-monitor/monitor.py`: po głównej pętli SL/TP dodaj blok `regime_mismatch_check`.
    2. Wczytaj `global_overrides.options_side_bias` z `learning-loop/state.json`.
    3. Pobierz SPY 5d return z `shared/market_data.py::compute_reaction_metrics('SPY')`.
    4. Jeśli `side_bias='long' AND contract_type='put' AND current_pl_pct < -0.15 AND spy_5d_return > 0.015`: place SELL_TO_CLOSE LIMIT @ bid (nie midpoint — agresywne wyjście).
    5. `client_order_id`: `exit-regime-{symbol}-{ts}`.
    6. `notify_exit reason='regime_mismatch'`.
    7. DTE guard: skip jeśli `DTE>14 AND strata < -25%` (można jeszcze odwrócić).

- [ ] [2026-05-09] **TP hit rate feedback loop: tighten TP multiplier when miss rate > 80% on 5+ placements** _(risk: low, effort: 1h, revisit: 2026-05-17)_
  - **Rationale:** `exit-tp-qqq699` canceled (tp_hit_rate 0% / 1 placed) to wczesny sygnał że TP=entry*1.8 jest za daleko w normalnych warunkach. `analyzer.py` liczy tp_hit_rate ale brak feedbacku do exit monitorów. Gdy `hit_rate < 0.20 AND tp_placed >= 5`, dynamicznie redukować TP multiplier do 1.4× — mniej per-trade zysku, dramatycznie lepsza wypełnioność.
  - **Sketch:**
    1. `analyzer.py compute_tp_hit_rate()`: dodaj per-strategy breakdown (obecnie 'unknown' bo brak client_order_id attribution w `exit-tp-*` orders).
    2. Payload `today_stats.tp_hit_rate`: dict keyed by strategy name.
    3. `adapter.py adapt_strategy()`: jeśli `tp_hit_rate[strategy] < 0.20 AND tp_placed >= 5`, zapisz `state['strategies'][strategy]['suggested_tp_multiplier'] = 1.4`.
    4. `options-exit-monitor`: wczytaj `suggested_tp_multiplier` z state.json, użyj zamiast hardcoded 1.8.
    5. **Uwaga:** to tylko options — stock TP/SL w exit-monitor ma osobną logikę.
