# Heuristic Proposals (LLM-generated)

> Open queue of heuristic ideas suggested by the daily LLM
> annotator + weekly retrospective. Tick the box `[x]` when
> implemented in `learning-loop/adapter.py`. Older entries
> kept indefinitely so we can audit which ideas worked.

- [x] [2026-05-07] Emergency exit orders (exit-emergency-*) muszą używać MARKET order ✅ DONE — exit-monitor.place_emergency_close + options-exit-monitor SL→MARKET (commits c4bc437, 0f7ce0b)
- [ ] [2026-05-07] TP orders niefilled — trailing stop dla pozycji >12h. **FRAMEWORK SHIPPED 2026-05-11** (`_check_trailing_stop` + peak-price tracking in `learning-loop/state.json::trailing_state` + `TRAILING_STOP_ENABLED=false` env flag default OFF). Gdy 10-day TP-hit-rate data potwierdzi że trailing > static TP (revisit **2026-05-17**), flip flag w workflow YAML — kod gotowy. Settings: trail_pct=8%, min_hold=12h. client_order_id: `exit-trail-*`. 6 smoke tests pass.
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

- [x] [2026-05-09] **Regime mismatch exit: proactive PUT close when side_bias=long + SPY uptrend** ✅ DONE 2026-05-11 — `_check_regime_mismatch` w options-exit-monitor (rate-checked before NEARDTH). Fires gdy: `options_side_bias=long AND PUT AND pl<=-15% AND SPY 5d>=+1.5%`. Guard: skip jeśli `DTE>14 AND pl in (-25%, -15%)` (zostaw room na reversal). Decision "REGIME" → MARKET sell-to-close. client_order_id: `exit-regime-*`. 7 smoke tests pass (PUT vs CALL detection, bias=short skip, pl>-15 skip, DTE>14 deep-loss-guard, fires correctly on AMZN PUT-style setup, fires on deep loss regardless of DTE).
  - **Rationale:** Gdy LLM ustawia `options_side_bias=long` w risk_on rally, stare PUT pozycje krwawią bez mechanizmu proaktywnego zamknięcia. Statyczny SL=entry*0.50 to za daleko — tracimy więcej niż konieczne zanim SL się aktywuje. Potrzebny dodatkowy trigger: jeśli `side_bias='long' AND pozycja jest PUT AND strata > -15% AND SPY 5d return > +1.5%`, zamknąć po midpoint niezależnie od SL.
  - **Sketch:**
    1. `options-exit-monitor/monitor.py`: po głównej pętli SL/TP dodaj blok `regime_mismatch_check`.
    2. Wczytaj `global_overrides.options_side_bias` z `learning-loop/state.json`.
    3. Pobierz SPY 5d return z `shared/market_data.py::compute_reaction_metrics('SPY')`.
    4. Jeśli `side_bias='long' AND contract_type='put' AND current_pl_pct < -0.15 AND spy_5d_return > 0.015`: place SELL_TO_CLOSE LIMIT @ bid (nie midpoint — agresywne wyjście).
    5. `client_order_id`: `exit-regime-{symbol}-{ts}`.
    6. `notify_exit reason='regime_mismatch'`.
    7. DTE guard: skip jeśli `DTE>14 AND strata < -25%` (można jeszcze odwrócić).

- [x] [2026-05-09] **TP hit rate feedback loop: tighten TP multiplier when miss rate > 80% on 5+ placements** ✅ DONE 2026-05-11 — `_apply_tp_feedback` helper w adapter.py: gdy `tp_hit_rate < 0.20 AND tp_placed >= 5`, set `state.strategies[s].suggested_tp_multiplier = 1.4`. `_effective_tp_mult()` w options-exit-monitor czyta state.json przy każdym tick'u, fallback do default TP_PREMIUM_MULT=2.20.
  - **Rationale:** `exit-tp-qqq699` canceled (tp_hit_rate 0% / 1 placed) to wczesny sygnał że TP=entry*1.8 jest za daleko w normalnych warunkach. `analyzer.py` liczy tp_hit_rate ale brak feedbacku do exit monitorów. Gdy `hit_rate < 0.20 AND tp_placed >= 5`, dynamicznie redukować TP multiplier do 1.4× — mniej per-trade zysku, dramatycznie lepsza wypełnioność.
  - **Sketch:**
    1. `analyzer.py compute_tp_hit_rate()`: dodaj per-strategy breakdown (obecnie 'unknown' bo brak client_order_id attribution w `exit-tp-*` orders).
    2. Payload `today_stats.tp_hit_rate`: dict keyed by strategy name.
    3. `adapter.py adapt_strategy()`: jeśli `tp_hit_rate[strategy] < 0.20 AND tp_placed >= 5`, zapisz `state['strategies'][strategy]['suggested_tp_multiplier'] = 1.4`.
    4. `options-exit-monitor`: wczytaj `suggested_tp_multiplier` z state.json, użyj zamiast hardcoded 1.8.
    5. **Uwaga:** to tylko options — stock TP/SL w exit-monitor ma osobną logikę.
- [x] [2026-05-09] **UUID strategy artifact pruning in analyzer — filter phantom state.json entries** ✅ DONE 2026-05-11 — `_is_uuid_key` + `_prune_uuid_keys` helpers w adapter.py, wywoływane na początku `adapt()`. Emituje rationale "pruned N UUID artifact strategy keys (...)". 7 UUID kluczy (fdeebe90, 62bd8628, b514d159, 2a526531, 5422a1fc, b4067979, 6b1dbd5a) zostanie wyczyszczone następnym daily-learning cronem.
- [x] [2026-05-09] **options_side_bias auto-clear gdy zero options trades w 7d window** ✅ DONE 2026-05-11 — `_reset_options_bias_if_no_data` helper w adapter.py. Reset gdy `options-momentum.trades_7d < 3`. State.json już pokazuje `options_side_bias: None` (zerowane wcześniej — być może manualnie); helper zapobiegnie regression.
- [x] [2026-05-10] **Flag enabled strategies with 0 trades after 10+ days tracked** ✅ DONE 2026-05-11 — `_flag_silent_strategies` w adapter.py: gdy `days_tracked >= 10 AND enabled=True AND trades_lifetime == 0 AND trades_7d == 0` → emit rationale "X: SILENT — enabled but 0 trades lifetime". Nie auto-disable — operator/LLM decyduje.
  - **Rationale:** 11 dni trackingu, 0 closed trades we wszystkich strategiach widocznych w today_stats. Heurystyka diagnostyczna: enabled=True + trades_lifetime=0 + days_tracked>=10 → warning w rationale.md. Challenger fix wdrożony: days_tracked = (today - SYSTEM_START_DATE).days gdzie SYSTEM_START_DATE = date(2026, 4, 29) stała w code_patch.
- [x] [2026-05-10] **UUID strategy key pruning in state.json** ✅ DONE 2026-05-11 (duplicate of 2026-05-09 — see entry above for impl details)
  - **Rationale:** 7 UUID-named kluczy zaśmieca state.json i maskuje prawdziwe strategie. Challenger wskazał brak backup step — dodany jako krok 0. Regex zaostrzony do dwuczęściowego UUID prefix zmniejszającego false positive risk. Revisit jutro (2026-05-11).
  - **Sketch:** 0. BACKUP: cp state.json state.json.bak-$(date +%Y%m%d) PRZED jakimkolwiek pruningiem.
1. _is_uuid_key(name): bool(re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-', name)) — dwuczęściowy prefix.
2. scripts/prune_uuid_strategies.py: load state.json, usuń pasujące klucze, save.
3. python -m scripts.prune_uuid_strategies (jednorazowo manualnie).
4. Weryfikacja: git diff state.json.bak-* learning-loop/state.json — upewnij się że usunięto tylko UUID klucze.
5. Commit + push.
- [ ] [2026-05-10] **Position P&L vs TP/SL distance audit (replaces naive stale-days alert)** _(risk: low, effort: 3-4h, revisit: 2026-05-13)_
  - **Rationale:** Challenger słusznie odrzucił STALE_DAYS=3 jako kryterium — 4 dni HOLD per STRATEGY.md v2.0 jest prawidłowy dla leveraged ETF. Nowe kryterium: (pnl_pct >= tp_threshold AND no exit order) OR (pnl_pct <= sl_threshold AND no exit order). Akcjonowalne i false-positive-safe.
  - **Sketch:** 1. compute_position_tp_sl_audit() w analyzer.py: GET /v2/positions + GET /v2/orders?status=open via Alpaca REST.
2. Per pozycja: pnl_pct = float(pos['unrealized_plpc']), tp_threshold = +0.10 (stocks proxy), +0.80 (options per entry*1.80), sl_threshold = -0.12 (emergency stop per STRATEGY.md v2.0).
3. has_exit_order = any open order z client_order_id matching 'exit-*' dla danego symbolu.
4. Flaguj SUSPECT: (pnl_pct >= tp AND NOT has_exit_order) OR (pnl_pct <= -|sl| AND NOT has_exit_order).
5. Append do rationale.md: 'position-audit: {symbol} pnl={pnl_pct:.1%} vs tp={tp:.1%} — no exit order found'.
6. Opcjonalnie: notify.py '[ALERT] Position TP/SL gap: {symbol}'.
Priorytety: najpierw options (AMZN PUT, tp=entry*1.80 znane), potem stocks.
- [x] [2026-05-10] WEEKLY EXP: Dup-position guard blokuje TICKERS_LONG — ❌ **HIPOTEZA FALSIFIED 2026-05-11** — GLD/RTX/XLE są OPEN ale **NIE są na TICKERS_LONG** (które to mega-cap momentum: AAPL/MSFT/GOOGL/NVDA/META/AMZN/TSLA/SPY/QQQ/COIN/MSTR/ARM/SMCI = 13 tickers). 0/13 blocked by dup-guard. Realny powód 7-dniowej ciszy: brak quality signals (RSI/breakout warunki) ALBO MSTR/SMCI ticker-pause via state.json (osobny mechanizm). Dup-position guard działa poprawnie.
- [ ] [2026-05-10] WEEKLY EXP: Options-momentum fill rate >65% post-midpoint — 🟡 **NIEZWERYFIKOWANE 2026-05-11** — od 2026-05-06 (AMZN PUT entry) zero nowych options trades przez 5+ dni. LLM Challenger w obu rundach 05-09/10 zwrócił uwagę: "options-momentum ABSENT z by_strategy". Pre-existing problem: options-monitor nie placuje nowych entries (osobny issue: RSI conditions / earnings guard / nie znaleziony in-budget kontrakt). EXP nie może być zweryfikowane dopóki options-monitor nie odpali nowej serii. **TODO osobno:** zdiagnozować czemu options-monitor cron 13:30-20:00 UTC pn-pt nie generuje proposals.
- [ ] [2026-05-10] WEEKLY EXP: SPY 5d return check jako pre-filter dla options direction (PUT tylko jeśli SPY 5d < -2%; CALL tylko jeśli SPY 5d > +2%) zredukuje AMZN-PUT-style blunders. Backtest koncepcji: w tygodniu risk_on (SPY 5d > +2%) AMZN PUT nie zostałby otwarty. (metric: Dodać 1-linijkowy log w options-monitor: 'SPY 5d return: X%'. Przez następny tydzień ręcznie porównaj: które opcje zostałyby zablokowane przez ten filter vs ile faktycznie otwarto. Jeśli filter blokowałby <30% sygnałów = implementować; jeśli >50% = za restrykcyjny.)
- [x] [2026-05-10] WEEKLY EXP: Reddit Curator E2E ✅ **CONFIRMED 2026-05-11 15:57 UTC** — commit `c054e4b` "llm: reddit_curate 2026-05-11_1557" zawiera real Curator output: 1 candidate (MSFT) skanowany, `selected_signals=[]` z brutalnym predator-grade rationale ("spike_ratio=99 artefakt zerowej 7d baseline; teza 'almost everybody talks about it' = stary konsensus; brak fresh katalizatora"). confidence=high. Pipeline działa end-to-end. (Side note: auto-merge.yml failnęła na race z reddit-monitor cron push tego samego momentu — fix `retry-on-non-fast-forward` shipped w tym samym batch'u.)
- [x] [2026-05-10] WEEKLY EXP: UUID strategy keys pruning ✅ DONE 2026-05-11 — `_prune_uuid_keys` helper w adapter.py, wywoływany w `adapt()`. Wyczyści 7 UUID kluczy następnym daily-learning cronem. Pre-implementation audit: żaden UUID nie miał trades_7d > 0 (potwierdzone pre-prune).
- [ ] [2026-05-11] **TP attribution fix — exit orders must embed strategy name in client_order_id** _(risk: low, effort: 1h, revisit: 2026-05-12)_
  - **Rationale:** Challenger potwierdził 5/5 sub-claims: tp_hit_rate['unknown'] blokuje trailing stop decision 2026-05-17 — zero danych bez fixa. Priority #1 przed jakąkolwiek decyzją kalibracyjną. Stress test: $0 dollar risk bezpośredni.
  - **Sketch:** 1. grep options-exit-monitor/monitor.py: format client_order_id przy place_limit_sell
2. zmien na f'exit-tp-options-momentum-{symbol}-{ts}' i f'exit-sl-options-momentum-{symbol}-{ts}'
3. grep exit-monitor/monitor.py: analogiczny fix stocks exits
4. update analyzer.py::_strategy_from_client_id(): regex 'exit-tp-{name}-' prefix
5. verify: nastepny daily run -> tp_hit_rate['options-momentum'] zamiast 'unknown'
- [ ] [2026-05-11] **Crypto/geo diagnosis — RSI-first verification before client_order_id audit** _(risk: low, effort: 1h, revisit: 2026-05-12)_
  - **Rationale:** MODIFIED per Challenger (3/5 sub-claims failed): hipoteza mismatch nieweryfikowalna bez RSI historii. BTC sideways 12 dni sugeruje RSI ~45-60 ponizej progow >70/<30 — dormant not broken. RSI-check first eliminuje 1h debugging non-buga.
  - **Sketch:** 1. Pull BTC/ETH daily bars za 14 dni via shared/market_data.py get_daily_bars
2. Policz RSI(14) — jesli MAX RSI <65 i MIN RSI >35: dormant not broken, koniec
3. Jesli RSI byl w zakresie >=2 razy: grep crypto-monitor/monitor.py client_order_id vs state.json keys
4. Analogicznie SPY proxy dla geo-xom
5. files dotykane tylko jesli krok 2 potwierdza aktywnosc sygnalow
- [ ] [2026-05-11] **Options entry cancellations audit — DAY expiry vs limit pricing gap** _(risk: low, effort: 1h, revisit: 2026-05-12)_
  - **Rationale:** fill_rate.options-momentum: canceled=2/15 (13.3%). Challenger wskazal ze entry-pricing mismatch moze byc wazniejszym blokerem closed profits niz TP calibration. Diagnoza: expired DAY orders poza session window vs limit zbyt daleko od mark.
  - **Sketch:** 1. Pull Alpaca orders status=canceled dla options, ostatnie 14 dni
2. Sprawdz canceled_at timestamp vs market session (13:30-20:00 UTC) — jesli after close: fix = nie placuj orders po 19:45 UTC
3. Sprawdz limit_price vs mark_price w momencie zlozenia — jesli delta >10%: midpoint logic zweryfikowac (post-2026-05-09 fix powinien byc juz w kodzie)
4. files: options-monitor/monitor.py (pricing logic), skrypt one-shot cancel audit
