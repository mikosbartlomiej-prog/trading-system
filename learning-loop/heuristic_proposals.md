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
- [ ] [2026-05-09] **UUID strategy artifact pruning in analyzer — filter phantom state.json entries** _(risk: low, effort: 1h, revisit: 2026-05-11)_
  - **Rationale:** State.json zawiera 7 UUID-format kluczy — artefakty Alpaca bracket order IDs. Root cause naprawiony (commit 2026-05-08), ale legacy entries nadal zaśmiecają LLM analizę 7 pustymi wpisami.
  - **Sketch:** W learning-loop/analyzer.py: dodać helper _is_uuid_key(name: str) -> bool z re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-', name). W _build_proposed_state() filtrować klucze strategies dict przed iteracją. Emitować jeden wiersz rationale: 'pruned N UUID artifact strategy keys'. Nie modyfikować state.json — tylko ignorować w analizie.
- [ ] [2026-05-09] **options_side_bias auto-clear gdy zero options trades w 7d window** _(risk: low, effort: 1h, revisit: 2026-05-13)_
  - **Rationale:** Challenger wskazał: options_side_bias=long utrzymywany przez 5 sesji bez żadnych danych options-momentum w by_strategy. Adapter powinien auto-resetować directional bias do null gdy brak supporting trade data — zapobiega evidence-free override.
  - **Sketch:** W learning-loop/adapter.py: w adapt_strategy() dla options-momentum: jeśli trades_7d == 0, wyzerować global_overrides.options_side_bias zamiast propagować z poprzedniego state. Alternatywnie: osobny pass w _build_proposed_state() resetujący options_side_bias gdy options-momentum.trades_7d < 3. Emitować rationale: 'options_side_bias reset to null — zero supporting data in 7d window'.
- [ ] [2026-05-10] **Flag enabled strategies with 0 trades after 10+ days tracked** _(risk: low, effort: ?, revisit: no specific date)_
  - **Rationale:** 11 dni trackingu, 0 closed trades we wszystkich strategiach widocznych w today_stats. Heurystyka diagnostyczna: enabled=True + trades_lifetime=0 + days_tracked>=10 → warning w rationale.md. Challenger fix wdrożony: days_tracked = (today - SYSTEM_START_DATE).days gdzie SYSTEM_START_DATE = date(2026, 4, 29) stała w code_patch.
- [ ] [2026-05-10] **UUID strategy key pruning in state.json** _(risk: low, effort: 1h, revisit: 2026-05-11)_
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
- [ ] [2026-05-10] WEEKLY EXP: Dup-position guard blokuje cały TICKERS_LONG scan gdy GLD/RTX/XLE są otwarte — system nie może dodać żadnej nowej długiej pozycji dopóki pierwsze 3 nie zostaną zamknięte. To wyjaśniałoby 7 dni ciszy po 2026-05-06. (metric: Audit price-monitor workflow logs (Actions → price-monitor runs 2026-05-07 do 2026-05-10): count 'pominiety (otwarta pozycja)' per ticker per run. Jeśli GLD/RTX/XLE = 3 skips każdy run = hipoteza potwierdzona. Target: znaleźć odpowiedź przed końcem 2026-05-12.)
- [ ] [2026-05-10] WEEKLY EXP: Options-momentum fill rate poprawi się do >65% z midpoint-based pricing (fix z 2026-05-09). Baseline: 40% fill rate przez 5 sesji (3 canceled / 10 placed). Oczekiwana poprawa: min 25 pp. (metric: Track options-momentum fill_rate w rationale.md codziennie przez pierwsze 3 sesje tygodnia 2026-05-12. Jeśli fill_rate >= 65% w 2/3 sesji = hipoteza potwierdzona.)
- [ ] [2026-05-10] WEEKLY EXP: SPY 5d return check jako pre-filter dla options direction (PUT tylko jeśli SPY 5d < -2%; CALL tylko jeśli SPY 5d > +2%) zredukuje AMZN-PUT-style blunders. Backtest koncepcji: w tygodniu risk_on (SPY 5d > +2%) AMZN PUT nie zostałby otwarty. (metric: Dodać 1-linijkowy log w options-monitor: 'SPY 5d return: X%'. Przez następny tydzień ręcznie porównaj: które opcje zostałyby zablokowane przez ten filter vs ile faktycznie otwarto. Jeśli filter blokowałby <30% sygnałów = implementować; jeśli >50% = za restrykcyjny.)
- [ ] [2026-05-10] WEEKLY EXP: Reddit Curator (Anthropic limit reset po 2026-05-09) generuje jakościowe sygnały dla META/MSTR/PLTR/TSLA (3 wzmianki każdy w 2026-05-09). Pierwsze potwierdzenie end-to-end Curator pipeline w warunkach produkcyjnych. (metric: Sprawdzić git log learning-loop/ za datę 2026-05-12 — szukać commita z pending-curation.json lub Curator narrative. Curator powinien wybrać 0-3 ticker z 4 kandydatów z uzasadnieniem P&L + size_multiplier override.)
- [ ] [2026-05-10] WEEKLY EXP: UUID strategy keys (7 wpisów: fdeebe90, 62bd8628, b514d159, 2a526531, 5422a1fc, b4067979, 6b1dbd5a) w state.json to legacy artifacts bez żadnych real trades. Pruning uprości state.json i usunie szum z per-strategy reportingu (te klucze pojawiają się w każdym daily summary jako '0 trades / 0% WR / $0' — noise przy 11 named strategies). (metric: Audit Alpaca orders history za ostatnie 14 dni — czy którykolwiek UUID odpowiada real client_order_id? Jeśli żaden = wykonać pruning per backlog (revisit 2026-05-11). Po prungingu: state.json powinien mieć 12 named strategies zamiast 19.)
