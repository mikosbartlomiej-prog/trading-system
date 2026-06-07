# Heuristic Proposals (LLM-generated)

> Open queue of heuristic ideas suggested by the daily LLM
> annotator + weekly retrospective. Tick the box `[x]` when
> implemented in `learning-loop/adapter.py`. Older entries

## P0 — Closed 2026-05-23 via v3.9.7

- [x] [2026-05-23] **Governor NEW_DAY peak reset bug — false RED_DAY_AFTER_GREEN with stale Alpaca last_equity** ✅ **DONE 2026-05-23 v3.9.7** — `shared/intraday_governor.py::update()` now seeds peak_pnl=0 + peak_equity=current_equity on new_day (instead of using Alpaca's stale daily_pl). Bug observed 2026-05-23 08:31 UTC: 0 positions + $0 intraday + $1,405 stale peak from Friday → false RED_DAY_AFTER_GREEN with max_gross_target=0.25 (would block Monday entries). Plus runtime_state.json manually reset to FLAT. 4 new unit tests in `tests/test_governor_new_day_reset_v397.py`.

## P1 — Closed 2026-05-22 EOD via v3.9.6 (commit 8f338dc)

- [x] [2026-05-22] **Fix `_do_recreate_exit_plan` — docstring says SELL LIMIT, code does MARKET CLOSE** ✅ **DONE 2026-05-22 v3.9.6** — `shared/remediation.py::_do_recreate_exit_plan` rewritten: fetches position (qty/entry/side), computes TP/SL from `aggressive_profile.json::exits.stocks_etf` (+18%/-6%), submits OCO via new `place_oco_exit` helper, position REMAINS OPEN. Asset-class routing: options skipped (options-exit-monitor handles), crypto skipped (Alpaca paper no OCO crypto). client_order_id `recreate-exit-{symbol}-{ts}`. 9 unit tests in `tests/test_recreate_exit_plan_v396.py`.
- [x] [2026-05-22] **Interim safety: add `REMEDIATION_DISABLE_RECREATE` env flag** ✅ **DONE 2026-05-22 v3.9.6** — env flag check at top of `_do_recreate_exit_plan` (returns `{ok: False, skipped: True}` when set). Default 'false' since proper fix landed same commit. Set in `autonomous-remediation.yml` env.
- [x] [2026-05-22] **Verify Alpaca paper supports GTC bracket children (test before changing default)** ✅ **PARTIALLY DONE 2026-05-22 v3.9.6** — code changed `place_stock_bracket` TIF day→gtc. **Production verification deferred to Monday 2026-05-25** morning-allocator first session (weekend market closed). Fallback exists: if Alpaca rejects → bracket creation fails cleanly → existing RECREATE path now safe (v3.9.6).
- [x] [2026-05-22] **Add audit JSONL emission to all remediation actions** ✅ **DONE 2026-05-22 v3.9.6** — `autonomous-remediation.yml` permissions:read→write + new "Commit audit journal" step with cherry-pick retry (v3.9.4.4 pattern). Decision statuses expanded: SKIPPED (was missing for skip paths). Existing `write_audit_event` calls per action now actually reach origin.


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
- [x] [2026-05-10] **Position P&L vs TP/SL distance audit (replaces naive stale-days alert)** ✅ DONE 2026-05-13 — `compute_position_audit()` w analyzer.py: per-asset-class thresholds (options TP +80%/SL -50%/emergency -12%; stocks TP +10%/SL -8%/emergency -12%); scans open positions vs open exit orders; SUSPECT lines lecą do today_stats.position_audit + rationale.md. v3.3 commit 6313350. 4 tests pass.
- [x] [2026-05-10] WEEKLY EXP: Dup-position guard blokuje TICKERS_LONG — ❌ **HIPOTEZA FALSIFIED 2026-05-11** — GLD/RTX/XLE są OPEN ale **NIE są na TICKERS_LONG** (które to mega-cap momentum: AAPL/MSFT/GOOGL/NVDA/META/AMZN/TSLA/SPY/QQQ/COIN/MSTR/ARM/SMCI = 13 tickers). 0/13 blocked by dup-guard. Realny powód 7-dniowej ciszy: brak quality signals (RSI/breakout warunki) ALBO MSTR/SMCI ticker-pause via state.json (osobny mechanizm). Dup-position guard działa poprawnie.
- [ ] [2026-05-10] WEEKLY EXP: Options-momentum fill rate >65% post-midpoint — 🟡 **NIEZWERYFIKOWANE 2026-05-11** — od 2026-05-06 (AMZN PUT entry) zero nowych options trades przez 5+ dni. LLM Challenger w obu rundach 05-09/10 zwrócił uwagę: "options-momentum ABSENT z by_strategy". Pre-existing problem: options-monitor nie placuje nowych entries (osobny issue: RSI conditions / earnings guard / nie znaleziony in-budget kontrakt). EXP nie może być zweryfikowane dopóki options-monitor nie odpali nowej serii. **TODO osobno:** zdiagnozować czemu options-monitor cron 13:30-20:00 UTC pn-pt nie generuje proposals.
- [x] [2026-05-10] **CLOSED 2026-05-16 v3.8.6** — superseded przez regime gate (PUT block gdy SPY RSI>75 + 5d>+2%). Implementacja w options-monitor::build_proposal + _get_spy_regime helper. Symetrycznie dla CALL.
- [x] [2026-05-10] WEEKLY EXP: Reddit Curator E2E ✅ **CONFIRMED 2026-05-11 15:57 UTC** — commit `c054e4b` "llm: reddit_curate 2026-05-11_1557" zawiera real Curator output: 1 candidate (MSFT) skanowany, `selected_signals=[]` z brutalnym predator-grade rationale ("spike_ratio=99 artefakt zerowej 7d baseline; teza 'almost everybody talks about it' = stary konsensus; brak fresh katalizatora"). confidence=high. Pipeline działa end-to-end. (Side note: auto-merge.yml failnęła na race z reddit-monitor cron push tego samego momentu — fix `retry-on-non-fast-forward` shipped w tym samym batch'u.)
- [x] [2026-05-10] WEEKLY EXP: UUID strategy keys pruning ✅ DONE 2026-05-11 — `_prune_uuid_keys` helper w adapter.py, wywoływany w `adapt()`. Wyczyści 7 UUID kluczy następnym daily-learning cronem. Pre-implementation audit: żaden UUID nie miał trades_7d > 0 (potwierdzone pre-prune).
- [x] [2026-05-11] **TP attribution fix — exit orders must embed strategy name in client_order_id** ✅ DONE 2026-05-12 — `_exit_client_order_id(reason, contract, strategy='options-momentum')` w options-exit-monitor; format zmieniony z `exit-{reason}-{contract}-{ts}` → `exit-{reason}-{strategy}-{contract}-{ts}`. Parser `_strategy_from_client_id` w analyzer.py rozpoznaje nowy format + ma fallback do per-symbol entry lookup dla legacy exits. `compute_tp_hit_rate` używa strategy z client_order_id (preferuje) + fallback. 9/9 parser tests pass + 2 integration tests (new format → options-momentum bucket, legacy → fallback przez symbol lookup). Odblokowuje trailing stop decision 2026-05-17.
  - **Rationale:** Challenger potwierdził 5/5 sub-claims: tp_hit_rate['unknown'] blokuje trailing stop decision 2026-05-17 — zero danych bez fixa. Priority #1 przed jakąkolwiek decyzją kalibracyjną. Stress test: $0 dollar risk bezpośredni.
  - **Sketch:** 1. grep options-exit-monitor/monitor.py: format client_order_id przy place_limit_sell
2. zmien na f'exit-tp-options-momentum-{symbol}-{ts}' i f'exit-sl-options-momentum-{symbol}-{ts}'
3. grep exit-monitor/monitor.py: analogiczny fix stocks exits
4. update analyzer.py::_strategy_from_client_id(): regex 'exit-tp-{name}-' prefix
5. verify: nastepny daily run -> tp_hit_rate['options-momentum'] zamiast 'unknown'
- [x] [2026-05-11] **Crypto/geo diagnosis — RSI-first verification before client_order_id audit** ✅ DONE 2026-05-12 — `compute_rsi_snapshot()` w analyzer.py: liczy RSI(14) dla SPY (stocks endpoint) + BTC/USD + ETH/USD (v1beta3 crypto endpoint). Zwraca `{symbol: {today, min_12d, max_12d, regime}}`. Wired do `today_stats.rsi_snapshot` — next daily-learning LLM payload zawiera macro context. Senior PM teraz widzi czy strategie są dormant przez warunki rynku (RSI nigdy nie hit threshold) vs faktycznie broken. RSI math 4/4 tests pass (uniform up → 100, uniform down → 0, sideways → ~50, insufficient → None).
  - **Rationale:** MODIFIED per Challenger (3/5 sub-claims failed): hipoteza mismatch nieweryfikowalna bez RSI historii. BTC sideways 12 dni sugeruje RSI ~45-60 ponizej progow >70/<30 — dormant not broken. RSI-check first eliminuje 1h debugging non-buga.
  - **Sketch:** 1. Pull BTC/ETH daily bars za 14 dni via shared/market_data.py get_daily_bars
2. Policz RSI(14) — jesli MAX RSI <65 i MIN RSI >35: dormant not broken, koniec
3. Jesli RSI byl w zakresie >=2 razy: grep crypto-monitor/monitor.py client_order_id vs state.json keys
4. Analogicznie SPY proxy dla geo-xom
5. files dotykane tylko jesli krok 2 potwierdza aktywnosc sygnalow
- [x] [2026-05-11] **Options entry cancellations audit — DAY expiry vs limit pricing gap** ✅ DONE 2026-05-12 — `compute_fill_rate` rozszerzony o breakdown `expired` (DAY orders timed out at market close) vs `manually_canceled` (SL-triggered cancels / manual). Plus `avg_minutes_to_cancel` + `max_minutes_to_cancel` from `submitted_at`/`canceled_at`/`expired_at` timestamps. Pozwoli odpowiedzieć: krótkie czasy do cancel = limit za niski (rejected-like), długie czasy = DAY expired (limit nigdy nie hit). Senior PM teraz może rozróżnić pricing problem od market structure problem. Smoke test: 4-order sample correctly classified (1 filled, 1 expired @ 270min, 1 manual cancel @ 5min, 1 rejected).
  - **Rationale:** fill_rate.options-momentum: canceled=2/15 (13.3%). Challenger wskazal ze entry-pricing mismatch moze byc wazniejszym blokerem closed profits niz TP calibration. Diagnoza: expired DAY orders poza session window vs limit zbyt daleko od mark.
  - **Sketch:** 1. Pull Alpaca orders status=canceled dla options, ostatnie 14 dni
2. Sprawdz canceled_at timestamp vs market session (13:30-20:00 UTC) — jesli after close: fix = nie placuj orders po 19:45 UTC
3. Sprawdz limit_price vs mark_price w momencie zlozenia — jesli delta >10%: midpoint logic zweryfikowac (post-2026-05-09 fix powinien byc juz w kodzie)
4. files: options-monitor/monitor.py (pricing logic), skrypt one-shot cancel audit
- [x] [2026-05-12] **Geo-xom pipeline audit** ✅ **PARTIALLY ADDRESSED 2026-05-16 v3.8.7** — geo-monitor full direct-execution refactor (`_classify_news_to_signals` + `execute_geo_signal` via `shared/alpaca_orders.execute_stock_signal`). Replaced deprecated routine path. Strategies re-enabled (geo-xom + others). Outstanding: 32 days SILENT post-refactor (only 7 days live) — tracked by new [2026-05-23] geo-strategy execution audit item (revisit 2026-05-26).
  - **Rationale:** Challenger SURVIVED 5/5. Strategia geo-xom włączona 13 dni, 0 tradów. Przed disable: odróżnić A (pipeline nie generuje XOM sygnałów — code bug) od B (sygnały blokowane przez guardy — calibration). Każdy wymaga innej akcji. $0 ryzyka pozycyjnego.
  - **Sketch:** 1. GitHub Actions → geo-monitor.yml → ostatnie 10 logów. Szukaj 'XOM', 'energy', 'oil', 'OXY', 'CVX'. 2. Scenariusz A (brak XOM content): disable geo-xom w state.json (rationale='pipeline nie generuje XOM sygnałów — needs code audit'); sprawdź geo-monitor/monitor.py SIGNAL_TICKERS lub equivalent. 3. Scenariusz B (sygnały blokowane): znajdź linie 'pominiety' + powód (concentration/VIX/drawdown); rozważ relaxation konkretnego guardu. 4. Deadline 2026-05-14.
- [x] [2026-05-12] **NVDA Reddit 48× spike — weryfikacja pipeline** ✅ **NOT BUG, closed 2026-05-13** — Reddit Curator correctly rejected NVDA pick on 2026-05-12 with merit reasoning (spike artefact, no fresh catalyst). Plus `|skew|<0.10 → UNCLEAR` fix in reddit-monitor. Pipeline working as designed; closing as historical reference.
  - **Rationale:** state.json.reddit_state.NVDA potwierdza 8 mentions zapisanych — pipeline działał do state write. Cisza (by_source={}) potwierdzona przez today_stats. Spike_ratio = 48× (Challenger correction: 8 ÷ 0.167 prior-only avg). NVDA = top backtest ticker (5 trades / 80% WR / 365d) — blokada pipeline ma najwyższy koszt alternatywny.
  - **Sketch:** 1. GitHub Actions → reddit-monitor.yml log 2026-05-12. KROK 1: szukaj 'NVDA' + wartość sentiment_skew. Jeśli skew < 0.3 → to jest blokada — nie email inbox. 2. Jeśli skew >= 0.3: Curator LLM decision — 'ZERO emit'? Inny ticker zajął MAX_ALERTS_PER_LANE=1 slot w tej samej rundzie? 3. Fix przy skew < 0.3: rozważ obniżenie progu z 0.3 na 0.2 dla spółek z backtestowanym edge (NVDA, AAPL). 4. AMD 4 mentions: analogiczna diagnostyka (AI semis cohort ruszył razem).
- [x] [2026-05-12] **Dodaj open_positions snapshot do today_stats** ✅ DONE 2026-05-13 (v3.3 commit 6313350) — `analyzer.py` calls `get_open_positions()` from `shared/risk_guards.py`; today_stats.open_positions populated. Senior PM has full portfolio visibility now.
- [x] [2026-05-12] **Annotate today_stats jako 24h window vs state.json lifetime** ✅ DONE 2026-05-13 (v3.3 commit 6313350) — `window_hours: 24` + `lifetime_from_state: {strategy: {trades_lifetime, pnl_usd_lifetime, win_rate_lifetime, consecutive_losses}}` added to today_stats. Eliminates Challenger Q2 confusion.
- [ ] [2026-05-12] **Options expired — zbierz bid/ask spread data przed decyzją o re-pricing** _(risk: low, effort: 1h, revisit: 2026-05-17)_
  - **Rationale:** Challenger odrzucił pełną implementację re-pricingu (sub-claims d/e/f/g UNFOUNDED — brak analizy mikrostruktury rynku). Problem jest realny: fill_rate.options-momentum expired=2, avg_minutes_to_cancel=325.6 min. Rehabilitation path per Challenger: sprawdź spread expired contracts, potem zdecyduj czy ask*1.01 ma sens.
  - **Sketch:** 1. GET /v2/orders?status=all&limit=50 — filtruj client_order_id prefix 'options-momentum', status=expired. 2. Dla każdego expired: pobierz contract symbol + expired_at. 3. GET /v1beta1/options/snapshots/{symbol} — sprawdź bid/ask w oknie expired_at ±15 min. 4. Jeśli spread < 5% premium: re-pricing ask*1.01 po 120 min viable → implementuj (2-3h effort). 5. Jeśli spread > 10%: re-pricing marginalny → zmień strategię wyboru kontraktów na ATM (spread ≤8%) lub TIF GTC+cancel_after.

<!-- ============================================================ -->
<!-- 2026-05-13 — v3.3 follow-ups + open backlog re-prioritization -->
<!-- ============================================================ -->

- [x] [2026-05-13] **Verify PROFIT_LOCK cascade fires correctly in production** ✅ **DONE 2026-05-22** — GIVEBACK_WARN cascade fired live 11:33 UTC 2026-05-22 (peak +$1,227 → current +$824, retrace 32.8%). FSM transition GREEN → GIVEBACK_WARN, max_gross 1.50→1.25, profit_floor $306.83 armed, email `[INTRADAY-WARN]` sent + verified by user screenshot. Full cascade chain (governor → audit → email → state persist → max_gross tighten) verified end-to-end. PROFIT_LOCK (35%) didn't trigger today but mechanism proven through GIVEBACK_WARN entry tier of same cascade.
- [ ] [2026-05-13] **Tune PROFIT_LOCK thresholds po 5 days production data** _(risk: low, effort: 1h, revisit: 2026-05-18)_
  - **Rationale:** Current thresholds: peak >=$1000, WARN @ 30%, LOCK @ 50%. Mogą być za konserwatywne (przepuszczają retrace) lub za agresywne (kasują winners za wcześnie). Po 5 dniach widzimy realne dane.
  - **Sketch:** 1. Read peak-tracker entries z rationale.md last 5 days. 2. Mark which days fired WARN/LOCK + outcome (czy harvest był rentowny?). 3. Tune: if too many false alarms → bump min peak to $1500; if missed late retrace → tighten LOCK 50% → 40%.
- [ ] [2026-05-13] **GH Actions monitor-health budget squeeze** _(risk: low, effort: 30min, revisit: 2026-05-17)_
  - **Rationale:** After repo-public flip (operator action pending), budget unlimited; we can flip cadences back. Or post-stabilization, drop monitor-health from hourly to every 6h. Saves ~600 invocations/month even on public.
  - **Sketch:** revisit po 5 dniach pełnej observability — czy faktycznie potrzebujemy hourly?

<!-- ============================================================ -->
<!-- 2026-05-13 P1 diagnostic sweep — 3 items closed, 1 new found -->
<!-- ============================================================ -->

- [x] [2026-05-13 P1] **Options-monitor zero entries diagnosis** ✅ NOT-A-BUG — `MAX_OPEN_OPTIONS=10` cap reached. Wczoraj 10+ open PUTs blokowało nowe entries. Po dzisiejszych zamknięciach 4 emergency PUTs (AAPL/GOOGL/SPY×2) sloty się zwolnią → options-monitor wróci do pracy automatycznie. NO ACTION NEEDED.

- [x] [2026-05-13 P1] **NVDA Reddit pipeline diagnosis** ✅ PIPELINE WORKS — Curator LLM correctly rejected NVDA on 2026-05-12 (commits a79938c, 6fca276): skew=-0.053 was neutral (near 0), top posts actually bullish, portfel already PUT-loaded. Drobny upstream fix shipped: gdy `|skew|<0.10` classify as UNCLEAR (let Curator decide direction) zamiast SELL_SHORT. Zapobiega FOMO classifications na noisy sentiment.

- [x] [2026-05-13 P1] **Geo-xom pipeline audit** ✅ STRUCTURAL FINDING — `geo-monitor` wysyła payload do Cloudflare worker → Routine, ale routine path deprecated od v2.2 (no direct execution). geo-xom strategy w state.json istniała ale **nigdy nie wykona XOM trade**. DISABLED in state.json. New backlog entry below for proper fix.

- [x] [2026-05-13] **CLOSED 2026-05-16 v3.8.7** — geo-monitor/monitor.py::_classify_news_to_signals (keyword→ticker map) + execute_geo_signal(via shared.alpaca_orders.execute_stock_signal). USE_ROUTINE=true legacy fallback. State.json re-enables geo-xom + geo-defense + geo-gold + geo-energy.
  - **Rationale:** geo-monitor sends payload to `CLOUDFLARE_GEO_WORKER_URL` → Claude.ai Exit Handler routine. Routine path deprecated v2.2 (defense/twitter/reddit/crypto already migrated to direct REST via `shared/alpaca_orders.py`). Geo-monitor wciąż używa routine = signals never execute. geo-xom strategy disabled until this fix.
  - **Sketch:** 1. Mirror `defense-monitor/monitor.py::classify_and_execute` pattern: parse priority/news/asset_map → decide ticker + side. 2. Energy news (oil/sanction/OPEC) → BUY XOM/CVX/USO/XLE. 3. Defense escalation news → BUY RTX/LMT/NOC. 4. Use `shared/alpaca_orders.execute_stock_signal` for each. 5. Per-event guards: VIX, daily-drawdown, concentration (already in shared/risk_guards). 6. Re-enable geo-xom + geo-defense + geo-gold strategies in state.json after deploy. 7. Iron rule: AUTO_EXECUTE_GEO=false default, manual flip after 1 week of email-only audit.

- [x] [2026-05-13 P1] **PROFIT_LOCK cascade v3.3 wiring smoke test** ✅ VERIFIED — All imports OK (peak_tracker, notify_peak_retrace, enrich_position with profit-lock branch, analyzer.compute_position_audit). State.json daily_peak initialized empty (will populate on first exit-monitor cron tick after market open 13:30 UTC). Real production fire pending market behavior — observation 2026-05-15 per backlog.
- [x] [2026-05-13] **CLOSED 2026-05-16 v3.8.6** — options-monitor::build_proposal z _get_spy_regime() + PUT_TREND_BLOCK_RSI=75 / PUT_TREND_BLOCK_5D_PCT=0.02. CALL symetrycznie. Effort 2h, dokładnie jak proposed.
  - **Rationale:** Options-monitor kupił 2 nowe PUTy (QQQ704, GOOGL385) PODCZAS rajdu z SPY RSI 82.4. RSI>72→PUT logika zakłada mean-reversion, ale bez weryfikacji czy overbought jest krótkoterminowe czy trend — staje się systematycznym fadem silnego trendu. Dziś to kosztowało dodatkową ekspozycję w złym kierunku w najgorszym możliwym momencie.
  - **Sketch:** W options-monitor/monitor.py, w logice propozycji PUT (warunek RSI > PUT_RSI_THRESHOLD):
1. Pobierz SPY bars via shared/market_data.py::get_daily_bars('SPY', 10)
2. Oblicz: spy_5d_return = (bars[-1]['close'] - bars[-6]['close']) / bars[-6]['close']
3. Oblicz spy_rsi = ostatni RSI(14) z bars
4. Jeśli spy_rsi > 75 AND spy_5d_return > 0.02: skip PUT, log 'REGIME GATE: SPY RSI={spy_rsi:.1f} + 5d={spy_5d_return:.1%} — zbyt silny trend, PUT zablokowany'
5. Symetrycznie: spy_rsi < 25 AND spy_5d_return < -0.02 → skip CALL
6. Progi (75, 2%) do config/aggressive_profile.json jako put_trend_block_rsi i put_trend_block_5d_return
7. Test cases: RSI=82 + 5d=+3.5% → 0 PUT proposals; RSI=74 + 5d=+1.8% → PUT allowed; RSI=80 + 5d=-0.5% → PUT allowed (spike bez trendu = reversal setup OK)
- [x] [2026-05-13] **CLOSED 2026-05-16 v3.8.6** — options-monitor _count_open_options_by_side() + PUT_CAP=5/CALL_CAP=5 w głównej pętli skanowania. OCC symbol parsing dla side detection.
  - **Rationale:** Dziś rano 15 otwartych PUTów = pełna jednostronna koncentracja. MAX_OPEN_OPTIONS=10 kontroluje łączną liczbę, ale nie dysproporcję call/put. Jeden silny rajd SPY wymazał cały portfel opcji naraz. Put/Call cap = hard limit na jednostronną ekspozycję niezależnie od liczby underlyings.
  - **Sketch:** W options-monitor/monitor.py, w bloku pre-order sprawdzającym MAX_OPEN_OPTIONS:
1. Po pobraniu otwartych pozycji US options via Alpaca /v2/positions, podziel na puts i calls
2. PUT detection: symbol.endswith('P' + 8-digit-strike) OR OCC-format zawiera 'P'
3. Jeśli nowa propozycja = PUT AND count(open_puts) >= PUT_CAP: skip, log 'SIDE CAP: {count} puts >= {PUT_CAP} — blokada PUT'
4. Jeśli nowa propozycja = CALL AND count(open_calls) >= CALL_CAP: skip analogicznie
5. PUT_CAP=5, CALL_CAP=5 do config/aggressive_profile.json (operator może tune)
6. Note: dzisiejszy scenariusz (15 PUTs) nigdy nie byłby możliwy z tym capo — max exposure $5k * 5 = $25k jednej strony
- [x] [2026-05-13] **CLOSED 2026-05-16 v3.8.6** — crypto-monitor::run_scan dodał scan_summary aggregate (scanned/no_signal/alt_cap/open_pos counts) + BTC dominance proxy log. check_crypto_signal już miał per-coin verbose; brakowało summary.
  - **Rationale:** Crypto-momentum i crypto-breakdown mają 0 trades w 14 dniach. Przy BTC RSI 64.3 to może być poprawne zachowanie — ale nie wiemy tego, bo logi nie pokazują per-coin powodów braku sygnału. Jeśli próg BTC dominance guard lub 24h bracket [3%,15%] blokuje wszystkie alts systemowo, a my tego nie wiemy, to mamy martwy monitor zjadający budżet Actions.
  - **Sketch:** W crypto-monitor/monitor.py — per-coin rejection diagnostics:
1. Dla każdej monety w COIN_TIERS: zaloguj RSI value + 24h_move_pct + rejection_reason
   Format: 'BTC/USD: RSI=64.3, 24h=+1.2% → SKIP (24h_move poniżej progu 3%)'
2. Zaloguj BTC dominance: 'BTC dominance: -0.5%/1h → PASS (guard OK)' lub 'BLOCK alt longs'
3. Zaloguj alt_positions_open: 'Alt positions: 0/3 — slot available'
4. Na końcu: 'Candidates: 0/11 coins passed all filters'
5. Cel: po 1 widocznym runie diagnozy wiemy (a) thresholdy OK lub (b) systematyczna blokada lub (c) Alpaca endpoint problem
6. Jeśli (a): zostaw, obserwuj do 2026-06-01; jeśli (b): tune thresholds; jeśli (c): fix
- [x] [2026-05-14] **CLOSED 2026-05-16 v3.8.7** — exit-monitor::place_emergency_close detects pre-market (UTC<13:30 weekday OR weekend) and returns {deferred: True, reason: 'pre_market_emergency_close'} for us_option/us_equity. Next cron after market open retries cleanly.
  - **Rationale:** Fill rate emergency 44.4% (4/9) z avg 149.6 min do anulowania — orders placed pre-market na illiquid options contracts. Fix: wykryć UTC godzinę; jeśli < 13:30 → opóźnić lub użyć time_in_force OPG zamiast DAY LIMIT.
  - **Sketch:** W emergency-close-positions.py i exit-monitor/place_emergency_close: sprawdź datetime.utcnow() < 13:30. Pre-market: zapisz do state.json::pending_emergency_closes lub użyj time_in_force='opg' dla opcji (at-open). Po 13:30: wyślij normalnie jako DAY LIMIT lub MARKET. Ważne: Alpaca OPG dostępne tylko dla equity, nie options — prawdopodobnie potrzebna kolejka w state.json + morning-allocator pickup. Pliki: scripts/emergency-close-positions.py, exit-monitor/monitor.py::place_emergency_close.
- [x] [2026-05-14] **CLOSED 2026-05-21** — diagnozowane przez LLM Senior PM 2026-05-19: 'crypto-momentum 0 trades correct — BTC RSI 64.3 < threshold 65, brak impulsu 3-15% w 24h'. Verbose logging v3.8.6 (scan_summary aggregate + per-coin RSI/move/vol) confirms pipeline healthy. crypto-breakdown disabled v3.8.1 (Alpaca paper LONG-only).
  - **Rationale:** 15 dni ciszy na 11-coin universe jest podejrzane nawet przy neutralnych RSI. BTC dominance guard, LLM Curator 429 fail-soft, lub Alpaca bars fetch mogą cicho blokować wszystkie sygnały bez widocznego błędu.
  - **Sketch:** 1. Manualny trigger crypto-monitor workflow i przejrzyj full log: czy logi per-coin RSI są widoczne? 2. Sprawdź BTC dominance fetch — czy API zwraca dane czy fail-open (co mogłoby permanentnie blokować alt-longs). 3. Sprawdź Curator LLM: czy 429 nie odrzuca wszystkich sygnałów (fail-soft powinien przekazywać dalej). 4. Sprawdź Alpaca bars dla Tier 2 coins: czy SOL/AVAX/LINK mają dane. 5. Jeśli wszystko OK → dodaj note do rationale.md że cisza jest poprawna (BTC RSI 63 < 65 threshold). Pliki: crypto-monitor/monitor.py (verbose per-coin logging), crypto-monitor/llm_curator.py (fail-soft check).
- [x] [2026-05-15] **DIAGNOSED 2026-05-19 by LLM** — crypto-momentum 0 trades correct: BTC RSI 64.3 / ETH 25.7 didn't meet entry threshold (move 3-15% in 24h). Not broken pipeline. crypto-breakdown disabled v3.8.1 (Alpaca paper crypto LONG-only). Verbose logging in v3.8.6 provides per-coin diagnostic.
  - **Rationale:** 342 scan-coin-okazji (38+ cron-ticki × 9 Tier-2 coins) bez JEDNEGO sygnału przy aktywnych rynkach krypto jest statystycznie podejrzane. Challenger dodał mierzalne kryterium sukcesu diagnozy — inkorporowane do sketcha.
  - **Sketch:** KROK 0 (kryterium sukcesu przed diagnozą): via Alpaca daily bars sprawdź czy DOWOLNY Tier-2 altcoin (SOL/AVAX/LINK/DOT/MATIC/LTC/BCH/UNI/AAVE) miał 24h move w [3%, 15%] w ostatnich 19 dniach. Jeśli TAK i nie było sygnału → pipeline broken. Jeśli NIE → correct silence, close. KROK 1: uruchom crypto-monitor.yml manualnie, sprawdź logi per-coin: RSI scan, 24h move bracket check, BTC dominance guard (-3% in 1h threshold), alt position cap (max 3, ale 0 open = nie blokuje). KROK 2: przetestuj Curator LLM — 429 fail-soft powinien przepuszczać heurystycznie. KROK 3: rozważ czy [3%, 15%] bracket jest za wąski przy wysokiej BTC dominance (alts mogą nie osiągać +3% nawet przy ogólnym wzroście krypto).
- [x] [2026-05-15] **CLOSED 2026-05-16 v3.8.6** — shared/allocator.py::generate_plan teraz wywołuje pdt_guard.get_pdt_status() i stempluje plan z pdt_mode/dt_remaining/dt_count/intent_for_buys. Trace log ostrzega gdy RESTRICTED/LOCKED.
  - **Rationale:** generate_plan() nie sprawdza PDT statusu — plan generuje N orders, execute blokuje M przez pdt_guard, tworząc mylące emaile (9/9 blocks jak 2026-05-14). Challenger poprawił proxy: asset_class zamiast nieistniejącego avg_hold_hours.
  - **Sketch:** 1. W shared/allocator.py::generate_plan() wywołaj pdt_guard.get_pdt_status() na początku. 2. Jeśli mode in [RESTRICTED, LOCKED]: ustaw intent='swing' dla wszystkich orders, wyklucz instrumenty gdzie asset_class='us_option' LUB instrument_windows.can_trade_now(symbol)=False dla aktualnej godziny — dostępny proxy, nie wymaga avg_hold_hours (pole nieistniejące w today_stats). 3. Dodaj pdt_mode do plan JSON jako metadata. 4. morning-allocator loguje '[PDT-SWING-ONLY]' w execution email. ~50 LOC + 2 testy.
- [x] [2026-05-15] **CLOSED 2026-05-16 v3.8.5** — options-exit-monitor TP time_in_force DAY→GTC (LIMIT TP nie expiruje już o EOD). SL/NEARDTH/REGIME/TRAIL/GOVERNOR pozostają MARKET. exit-monitor stocks już używał MARKET fallback.
  - **Rationale:** fill_rate.emergency: placed=1, filled=0, expired=1, avg_minutes_to_cancel=390 — DAY TIF LIMIT emergency close wygasł po 6.5h bez realizacji. Pozycja mogła pozostać otwarta przez noc bez exit planu. Structural failure trybu awaryjnego — wymaga fixa przed otwarciem nowych pozycji.
  - **Sketch:** 1. Zidentyfikuj symbol: sprawdź Alpaca dashboard orders z 2026-05-14/15 z client_order_id prefix 'exit-emergency-*' lub 'emergency-close-*', TIF=day, status=expired. 2. exit-monitor/monitor.py::place_emergency_close: zmień LIMIT+DAY na MARKET dla CLOSE_EMERGENCY recommendation (us_equity i us_option). Alternatywnie użyj DELETE /v2/positions/{symbol_encoded} jak emergency_close_20260514.py — omija paper API buying-power bugs dla opcji. 3. Sprawdź czy exit-monitor ma retry logic po wygaśnięciu ORDER — jeśli nie, dodaj: po otrzymaniu expired status dla emergency order → natychmiastowy retry MARKET. 4. options-exit-monitor: SL/NEARDTH/GOVERNOR/REGIME już używają MARKET (v3.3) — verify nie regresowały. 5. Test: mock place_emergency_close → assert order_type='market' OR HTTP method='DELETE'.
- [x] [2026-05-15] **CLOSED 2026-05-16 v3.8.5** — shared/alpaca_orders.py::_client_order_id strict validation: hard-reject empty/None/UUID-prefixed strategy names; warn na 'auto'. Plus analyzer.py UUID regex detection w _strategy_from_client_id.
  - **Rationale:** fill_rate.unknown: placed=1, filled=0, manually_canceled=1, avg_minutes_to_cancel=647.7 — order bez strategy attribution siedział 10.8h. Bug w client_order_id tagging powoduje utratę P&L attribution w analyzer.
  - **Sketch:** 1. Znajdź order: Alpaca dashboard orders z 2026-05-14/15, manualnie canceled, bez rozpoznawalnego prefix (opcja: puste client_order_id lub raw UUID). 2. Zidentyfikuj monitor: sprawdź logi GitHub Actions z tego dnia — który workflow uruchomił order bez prefix. 3. Fix: każde wywołanie place_stock_bracket/place_crypto_order/place_simple_buy musi mieć explicit client_order_id z rozpoznawalnym strategy prefix. 4. Dodaj assertion w shared/alpaca_orders.py: jeśli client_order_id jest None → raise ValueError('client_order_id required for attribution') zamiast cichego None.- [ ] [2026-05-17] **Trailing stop decision deferred: tp_hit_rate empty, options N=1 — revisit 2026-06-01** _(risk: low, effort: 1h, revisit: 2026-06-01)_
  - **Rationale:** Scheduled review 2026-05-17 niewykonalny: tp_hit_rate={}, options-momentum trades_lifetime=1. Trailing stop framework gotowy w options-exit-monitor (TRAILING_STOP_ENABLED env flag, 8%% trail, 12h min-hold) — tylko decyzja aktywacji wymaga min. 10 options trades z TP data.
  - **Sketch:** Warunek rewizji: options-momentum trades_lifetime >= 10. Kroki: 1) pobierz tp_hit_rate z learning-loop/history/*.md dla ostatnich 10 trade-ow; 2) jeśli hit_rate < 30%% -> flip TRAILING_STOP_ENABLED=true w options-exit-monitor workflow; 3) jeśli >= 50%% -> static TP ok, zamknij temat; 4) 30-50%% = dyskusja z userem. Pliki: options-exit-monitor/monitor.py (TRAILING_STOP_ENABLED env var), learning-loop/history/*.md (tp_hit_rate metric).
- [x] [2026-05-17] **CLOSED 2026-05-21 v3.8.9** — root cause: UUID-prefixed client_order_ids parsed as fake 'unknown' strategy. Fixed in v3.8.5 _strategy_from_client_id UUID detection + strict _client_order_id validation. Plus v3.8.8 added open_samples + open_symbols to compute_fill_rate for diagnostic visibility. Plus v3.8.9 aggressive entry pricing (ask/bid not mid) fixes geo-USO/OXY/GLD 37% fill rate.
  - **Rationale:** 6 zleceń bez strategy attribution i 0%% fill rate destruuje P&L analytics i może oznaczać otwarte LIMIT buy-y z planu allocatora siedzące w order book. Muszą być zdiagnozowane przed otwarciem rynku w poniedziałek żeby nie kolizować z nowym planem allocatora.
  - **Sketch:** GET /v2/orders?status=open — sprawdź czy 6 otwartych zleceń bez proper client_order_id prefix. Jeśli to morning-allocator BUY-y (PDT-blocked -> LIMIT nie wypełnione -> expired): anuluj pozostałości, poczekaj na PDT reset (~2026-05-22). Jeśli ID bug: napraw alpaca_orders.py::_client_order_id() i dodaj assert no UUID prefix. Pliki: shared/alpaca_orders.py, learning-loop/analyzer.py::_strategy_from_client_id.
- [x] [2026-05-17] **Suppress SILENT adapter flag for strategies within 5 days of re-enable** ✅ **DONE 2026-05-20 v3.9.0** (commit `4ad5ee4`) — `adapt_strategy()` stamps `enabled_at` on False→True transition (auto-resume from paused_until OR external override). `_flag_silent_strategies()` skips when `(today - enabled_at).days < 5`. Malformed/missing enabled_at falls through to normal silent check. State.json backfilled for 6 strategies (geo-defense/energy/gold/xom @ 2026-05-16, options-momentum + crypto-momentum @ 2026-05-19). 10 unit tests in `tests/test_silent_grace.py`. Verified working — geo-* strategies passed 5-day grace (expired 2026-05-21), now showing SILENT correctly since trades_lifetime=0; options-momentum + crypto-momentum still within grace (expires 2026-05-24).
- [x] [2026-05-17] **CLOSED 2026-05-21 v3.8.9** — duplicate of above. Covered by v3.8.5 UUID detection + v3.8.8 open_samples + v3.8.9 aggressive entry.
  - **Rationale:** 6 zleceń strategy=unknown z zerem wszystkich outcome counters (filled=0, canceled=0, expired=0, rejected=0) to matematyczna niemożliwość — każde Alpaca order musi mieć status. Przed Monday session trzeba zidentyfikować skąd pochodzą i naprawić attribution, inaczej będziemy tracić ślad wypełnionych tradów.
  - **Sketch:** 1. Fetch GET /v2/orders?status=all&after=2026-05-16T00:00:00Z&limit=50
2. Zidentyfikuj zlecenia gdzie _strategy_from_client_id zwraca 'unknown'
3. Jeśli UUID format (przed v3.8.5): dodaj pre-filter — te legacy orders pomiń w fill_rate counter
4. Jeśli nowy format (po v3.8.5): znaleźć monitor produkujący nieparsowalny client_order_id i naprawić
5. Upewnij się że outcome counters zliczają też strategy=unknown (nie tylko named strategies)
- [x] [2026-05-18] **CLOSED 2026-05-21 v3.8.9** — learning-loop/analyzer.py::compute_equity_gap_alert flags equity move > $500 with 0 attributed trades. WARN severity if |delta| >= $1000. Surfaces to today_stats + rationale.md. Wired in payload before LLM call.
  - **Rationale:** Equity -$1,187 w 24h przy cumulative_trades=0 i fill_rate.unknown=6 placed/0 outcomes. Każdy Alpaca order musi mieć finalny status (filled/canceled/expired/rejected) — anomalia wskazuje na ghost orders lub bug atrybucji ukrywający fills. Bez diagnozy learning loop nie widzi realnych strat i nie może adaptować strategii.
  - **Sketch:** 1. analyzer.py: jeśli abs(equity - starting_equity) > 500 AND cumulative_trades == 0 AND fill_rate.get('unknown',{}).get('placed',0) > 0 -> append 'EQUITY_GAP_ALERT: $X niewyjasniona zmiana, N ghost orders' do deterministic_rationale. 2. Zidentyfikowac zrodlo 6 unknown orders: query Alpaca /v2/orders?status=all&after=<24h ago>, filtruj po client_order_id ktore nie parsuja zadnego known prefix (entry-/exit-/options-/alloc-/op-correction-/emergency-close-). 3. Zbadac czy morning-allocator w v3.8.6+ uzywa prawidlowego client_order_id formatu — jesli format zmienil sie i _strategy_from_client_id nie rozpoznaje, to zrodlo ghost. 4. Krotkoterminowy patch: ALLOCATOR_LEVEL_TAGS w adapter.py rozszerzyc o kazdy prefix ktory morning-allocator generuje. Pliki dotkniate: learning-loop/analyzer.py, learning-loop/adapter.py (ALLOCATOR_LEVEL_TAGS), shared/alpaca_orders.py (_client_order_id format audit).
- [x] [2026-05-18] **CLOSED 2026-05-21 v3.8.9** — partially superseded by v3.8.5 (no new UUID artifacts created) + v3.8.8 (open_samples surface client_order_ids for manual lookup). Full Alpaca cross-ref would be incremental value over current diagnostic — skipped.
  - **Rationale:** 6 placed / 0 filled pod 'unknown' strategią to trzeci dzień z rzędu tej anomalii. Bez identyfikacji źródła (alloc-* vs options-* vs UUID-artifact) P&L pozostaje ślepy i atrybueja bezużyteczna.
  - **Sketch:** W analyzer.py na końcu analyze(): wywołaj GET /v2/orders?status=all&limit=50&after=<yesterday_utc_midnight>. Dla każdego rozkazu z client_order_id pasującym do wzorca UUID (8-4-4-4-12 hex) lub pustym, dodaj do today_stats.fill_rate_unknown_audit: [{order_id, client_order_id, symbol, side, status, qty}]. Append warning do deterministic_rationale: 'X unattributed orders found: [symbols]'. To jednoznacznie określi skąd pochodzi atrybucja 'unknown'.
- [ ] [2026-05-18] **Defer AAPL concentration boost to first 5 live momentum-long trades** _(risk: low, effort: needs design, revisit: 2026-06-01)_
  - **Rationale:** Dziś (2026-05-18) to planowana data review dla AAPL boost (backtest: 7 trades / 71% WR / +$3,379). Ale lifetime_from_state nie zawiera żadnej strategii momentum-long — 0 żywych obserwacji. Boost bez live data to hazard na backtest.
  - **Sketch:** Żadnej zmiany state.json dzisiaj. Trigger aktywacji: gdy momentum-long lifetime_trades >= 5 i win_rate_lifetime >= 0.60 → size_multiplier 1.0 → 1.2. Przy >= 15 trades i WR >= 0.65 → += 0.1 (max 1.4). Tickers poza AAPL/SPY: utrzymać w universe do 30 trades aggregate — sample za cienki do trim-u.
- [x] [2026-05-18] **CLOSED 2026-05-21 v3.8.9** — learning-loop/analyzer.py::compute_oversold_alerts flags RSI<=30 (oversold pre-signal) and RSI>=75 (overbought fade-risk) per symbol in rsi_snapshot. Surfaces to today_stats['rsi_alerts'] + rationale.md.
  - **Rationale:** ETH RSI 25.9 to skrajne wyprzedanie, historycznie zbieżne z lokalnymi dnami. crypto-momentum czeka na momentum (RSI 45+), ale bez pre-alert analizator nie widzi nadchodzącego setup-u. Wczesny log = szybsza reakcja gdy RSI odbija.
  - **Sketch:** W analyzer.py: jeśli rsi_snapshot.ETH/USD.today < 30, append do deterministic_rationale: 'ETH RSI <30 oversold — crypto-momentum may fire on bounce; watch RSI >= 38 as early warning'. Analogicznie dla BTC < 35. Nie zmienia state.json — czysta obserwacja diagnostyczna.
- [x] [2026-05-19] **CLOSED 2026-05-21 v3.8.6/v3.8.9** — analyzer.py::_is_close extended z prefixami: alloc-exit-, alloc-reduce-, op-correction-, emergency-close-, operational-correction- + Alpaca position_intent=sell_to_close/buy_to_close fallback (v3.8.6). Geo-* używają geo-defense/energy/xom/gold strategy names (v3.8.7) — analyzer rozpoznaje via _strategy_from_client_id. Weryfikacja: następny daily-learning 2026-05-22 04:00 UTC pokaże non-zero attribution.
  - **Rationale:** +$1,350 nieatrybutowanego equity gain (4. dzień z rzędu). USO/OXY/GLD otwarte w fill_rate.unknown potwierdzają że geo-energy i geo-gold GENERUJĄ zlecenia po refaktorze. alloc-exit (4/4 filled) i alloc-reduce (6/6 filled) też nieatrybutowane. Bez atrybucji adapter podejmuje decyzje o sizing bez wiedzy czy system zarabia — to krytyczna ślepota.
  - **Sketch:** 1. analyzer.py::_is_close(): dodaj 'alloc-exit-', 'alloc-reduce-' jako close-action prefixes (równolegle do 'exit-*'). 2. _strategy_from_client_id(): dodaj 'geo-defense-', 'geo-energy-', 'geo-gold-', 'geo-xom-' jako strategy markers. 3. reconstruct_trades(): dla alloc-reduce SELL, szukaj poprzedniego allocator-rebalance BUY na ten sam symbol (FIFO pairing). 4. Dodaj test: mock BUY 'allocator-rebalance-AMD-1234' + SELL 'alloc-reduce-AMD-1235' → expects 1 completed trade attributed to 'allocator-rebalance'. 5. Po fix: sprawdź czy +$1,350 staje się atrybutowane w następnym daily-learning runie.
- [x] [2026-05-19] **CLOSED 2026-05-21 v3.8.9** — superseded przez aggressive entry pricing w shared/alpaca_orders.py::execute_stock_signal (ask BUY / bid SHORT, więcej agresywne niż mid+0.25%). _aggressive_entry() helper. Geo-USO/OXY/GLD/XOM/CVX powinno mieć fill rate 70-90% (vs 37%).
  - **Rationale:** Fill rate 37% na geo-zleceniach (USO/OXY/GLD) z avg_cancel=82.4 min oznacza, że limity są składane poniżej aktualnego ask. Ten sam problem miał options-monitor przed midpoint-pricing fix z 2026-05-09. Szybki 1h fix: geo-monitor/monitor.py::execute_geo_signal pobiera Alpaca quote i używa ask*1.0025 dla BUY zamiast close_price.
  - **Sketch:** W geo-monitor/monitor.py::execute_geo_signal: (1) przed wywołaniem execute_stock_signal, dodaj Alpaca REST call do /v2/stocks/{symbol}/quotes/latest (papier API, te same klucze). (2) limit_price = float(quote['ask_price']) * 1.0025 dla BUY, float(quote['bid_price']) * 0.9975 dla SELL. (3) Fallback: jeśli quote endpoint zwróci błąd, użyj close_price * 1.005 (szerszy buffer z close). (4) Przekaż limit_price do shared/alpaca_orders.py::place_stock_bracket (sprawdź signature — może wymagać dodania parametru). Test: mockuj /v2/stocks/USO/quotes/latest → ask=78.50; assert limit_price == 78.50 * 1.0025 = 78.696. Precedens: options-monitor/monitor.py::_resolve_limit_price (midpoint z 2026-05-09). Pliki: geo-monitor/monitor.py, shared/alpaca_orders.py (opcjonalnie).- [ ] [2026-05-21] **Per-monitor fill rate attribution via client_order_id prefix** _(risk: low, effort: 2-3h, revisit: 2026-05-28)_
  - **Rationale:** fill_rate.unknown 0% na 28 zleceniach to blinder operacyjny. Kluczowe pytanie: czy te 28 to wejściowe sygnały geo/defense/twitter które nie trafiają w rynek, czy TP exits z portfela alokatorowego czekające na cel +14%? Bez odpowiedzi każdy fix limitów to strzelanie na ślepo.
  - **Sketch:** 1. Każdy monitor który wywołuje execute_stock_signal prefixuje client_order_id: geo-monitor -> 'geo-{sym}-entry-{ts}', defense-monitor -> 'def-{sym}-entry-{ts}', twitter-monitor -> 'twit-{sym}-entry-{ts}'. 2. Allocator BUY entries -> 'alloc-buy-{sym}-{ts}' (distinct od alloc-tp). 3. analyzer.py::_strategy_from_client_id() rozszerza regex: r'^(geo|def|alloc|twit|reddit)-' -> source category. 4. fill_rate dict rozbity per-source: fill_rate.geo-monitor, fill_rate.defense-monitor, fill_rate.alloc-tp itp. 5. Adapter flaguje per-source fill_rate alert zamiast globalnego unknown. Docelowo fill_rate.unknown znika.
- [ ] [2026-05-23] **Geo-strategy execution audit: 32 days SILENT — verify v3.8.7 direct-exec chain before disable** _(risk: low, effort: 1h, revisit: 2026-05-26)_
  - **Rationale:** Geo-defense/energy/gold/xom mają 0 trades w 32 dniach. Przed disable'em trzeba odróżnić 'brak qualifying newsów' od 'broken execution chain'. V3.8.7 (2026-05-16) dodał direct-exec przez execute_stock_signal — nie wiemy czy ta ścieżka kiedykolwiek odpalała w produkcji.
  - **Sketch:** 1. GH Actions -> geo-monitor workflow logs ostatnie 7 dni
2. Szukaj '_classify_news_to_signals' hits — ile razy znalazł kwalifikujący news?
3. Szukaj 'execute_geo_signal' hits — ile razy weszło do execution path?
4. Jesli 0 klasyfikacji: środowisko spokojne, strategie poprawnie uśpione — NIE disable
5. Jesli klasyfikacja jest ale 0 execute_geo_signal: wiring bug w v3.8.7 — fix urgent
6. Jesli execute fires ale 0 Alpaca orders: sprawdź VIX/drawdown/concentration guards
7. Disable tylko jesli bug potwierdzony AND brak qualifying events >21 dni
- [ ] [2026-05-23] **Strategy attribution fix: 7/7 allocator fills tagged 'unknown' — verify client_order_id format post-v3.9.6** _(risk: low, effort: 1h, revisit: 2026-05-26)_
  - **Rationale:** fill_rate pokazuje 7 fills attributed to 'unknown'. V3.8.5 miało naprawić UUID pollution — albo tag alloc-rebalance nie przechodzi przez _strategy_from_client_id, albo allocator nie ustawia client_order_id. Kiedy wszystko trafia jako unknown, TP hit rate i strategy scorecard są ślepe.
  - **Sketch:** 1. Sprawdź client_order_id format w allocations/2026-05-22.execution.json dla placed orders
2. Porownaj z _strategy_from_client_id regex patterns w analyzer.py
3. Jesli format alloc-rebalance-<ticker>-<ts> nie jest parsowany: add regex case w _strategy_from_client_id
4. Jesli allocator nie ustawia client_order_id w ogole: dodaj w _exec_buy() w allocator.py
5. Verify w nastepnym daily run — fill_rate.alloc-rebalance powinien zastapic fill_rate.unknown
- [ ] [2026-05-23] **Auto-disable geo-strategies after 10 silent days post-enable_at** _(risk: medium, effort: 2-3h, revisit: 2026-05-26)_
  - **Rationale:** Cztery strategie geo (defense/energy/gold/xom) mają 0 transakcji przez 7 dni od refaktoru v3.8.7 (enabled_at=2026-05-16). Ręczny review co kilka dni jest kosztowny i reaktywny. Adapter powinien automatycznie wyłączać strategie bez dowodu execution po 10 dniach od enabled_at — eliminuje potrzebę manualnej interwencji i zamyka pętlę.
  - **Sketch:** 1. Nowa funkcja heuristic_no_execution_disable(name, stats, state) w adapter.py.
2. Warunki: name.startswith('geo-') AND enabled=True AND trades_lifetime==0 AND enabled_at in state.
3. Oblicz: days_since_enable = (today - date.fromisoformat(state[name]['enabled_at'])).days.
4. Jezeli days_since_enable >= 10: return True, 'AUTO-DISABLED: 0 trades 10+ days post-enable_at — no execution evidence'.
5. Wire-in adapt() po silent-flag warnings, przed win_rate thresholds.
6. enabled -> False, paused_until=None; wymaga manualnego re-enable (lub dowodu ze geo-monitor pipeline dziala).
7. Docelowo uogolnic prefix do konfigurowalnej listy.
- [ ] [2026-05-24] WEEKLY EXP: Geo-monitor limit pricing fix (ask-price BUY) zwiększy fill rate z 0% do >50% w pierwszych 5 sesjach po wdrożeniu (2026-05-27 do 2026-05-30). (metric: fill_rate dla geo-defense/geo-energy/geo-gold w history/<date>.md: >50% przez min 3 z 5 sesji roboczych)
- [ ] [2026-05-24] WEEKLY EXP: ETH RSI=19.7 jest blisko historycznego bounce'u kapitulacyjnego. Crypto-momentum z 1.5x (PR #9) wygeneruje pierwszy profitable crypto trade w ciągu 5 sesji po otwarciu (2026-05-27 do 2026-05-31). (metric: crypto-momentum: min 1 zamknięty trade z P&L > 0 i size >= 1.5x base w tygodniu 2026-05-27 do 2026-05-31)
- [ ] [2026-05-24] WEEKLY EXP: Options-monitor nie generuje nowych fills po re-enable 2026-05-19 z powodu premium poza budżetem lub brak setupów przy SPY RSI 72-73 (PUT-gate aktywne). Manual workflow trigger + log review ujawni czy to problem pipeline'u czy rynku. (metric: options-momentum: min 1 nowy zamknięty trade (poza istniejącym N=1) do 2026-05-31)
- [ ] [2026-05-24] WEEKLY EXP: Geo-strategies po fix limitów wykażą min 1 fill dla co najmniej jednej strategii do 2026-05-30. Jeśli nie — pipeline jest strukturalnie uszkodzony i pricing nie jest jedynym problemem. (metric: geo-defense LUB geo-energy LUB geo-gold LUB geo-xom: min 1 filled order do 2026-05-30 (EOD))
- [ ] [2026-05-24] WEEKLY EXP: Memorial Day 2026-05-25 instrument_windows.py poprawnie blokuje morning-allocator o 13:35 UTC. Zero zleceń w poniedziałek = poprawne zachowanie systemu. (metric: morning-allocator log 2026-05-25: 'market closed' lub 'holiday' — zero placed orders)
- [ ] [2026-05-25] **Holiday-aware SILENT threshold: licz trading days nie calendar days** _(risk: low, effort: 2-3h, revisit: 2026-06-01)_
  - **Rationale:** Adapter flaguje 6 strategii SILENT po '36 dniach tracked' ale ~14 z tych dni to weekendy i święta US (włącznie z Memorial Day) — 0 możliwości wejścia. Efektywny czas rynkowy to ~22 sesje. Próg silent powinien bazować na sesjach rynkowych (trading days), nie dniach kalendarzowych. Eliminuje fałszywe alarmy dla strategii w weekend/holiday periods.
  - **Sketch:** W adapter.py _flag_silent_strategies(): zamiast (today - enabled_at).days oblicz liczbę dni roboczych wykluczając US holidays. Opcja A (prosta): numpy.busday_count z US holiday list (MLK, Presidents, Memorial, Independence, Labor, Thanksgiving, Christmas). Opcja B (dokładna): dodaj 'trading_days_active' counter do state.json per strategy, inkrementowany przez analyzer.py tylko gdy Alpaca /v2/clock is_open=true w momencie uruchomienia. Próg silent: 15 trading_days zamiast obecnych 21 calendar_days (wzrost do ~30 calendar_days). Pliki: learning-loop/adapter.py (_flag_silent_strategies), learning-loop/state.json (nowe pole per strategy), learning-loop/analyzer.py (inkrementacja counter).
- [ ] [2026-05-25] **Auto-disable geo strategies after N days with 0 trades (deadline enforcement)** _(risk: low, effort: 1h, revisit: 2026-05-30)_
  - **Rationale:** Geo-defense/energy/gold/xom mają twardy deadline 2026-05-30 ustawiony manualnie w rationale. Bez automatyzacji operator musi pamiętać o ręcznym disable. Heurystyka porównuje enabled_at z datą dzisiejszą i liczbą trades_lifetime — jeśli oba progi przekroczone, auto-disable i zapis rationale.
  - **Sketch:** W adapter.py: def _auto_disable_stale_enabled(strategies, today, max_days_silent=42):
    for name, s in strategies.items():
        if not s.get('enabled'): continue
        enabled_at = s.get('enabled_at')
        if not enabled_at: continue
        days_enabled = (today - date.fromisoformat(enabled_at)).days
        trades_lt = s.get('trades_lifetime', 0)
        if days_enabled >= max_days_silent and trades_lt == 0:
            s['enabled'] = False
            s['paused_until'] = None
            s['rationale'] = f'AUTO-DISABLED {today} — {days_enabled} days enabled, 0 trades lifetime'
Wire do adapt_strategy() po pętli warm-up/cool-down.
- [ ] [2026-05-26] **Auto-disable geo-strategies on deadline when lifetime trades == 0** _(risk: medium, effort: 2-3h, revisit: 2026-05-30)_
  - **Rationale:** Cztery geo-strategie mają twardy deadline 2026-05-30 z 38 dniami i 0 wypełnieniami. Deadline istnieje jako tekst w rationale, nie jako kod. Bez auto-disable mechanizmu, strategie kontynuują konsumowanie VIX/drawdown guard calls bez żadnego efektu, i wymagają ręcznej interwencji operatora per sesję.
  - **Sketch:** 1. Add 'deadline' date field to geo-* entries in state.json (e.g. '2026-05-30')
2. In adapter.py adapt(): for each strategy, if state has 'deadline' AND deadline < today AND trades_lifetime == 0: set enabled=False, rationale='Auto-disabled: deadline {} reached with 0 lifetime fills'.format(deadline)
3. Append to rationale_lines: 'auto-disabled by deadline: {name}'
4. Target: geo-defense, geo-energy, geo-gold, geo-xom
5. Tests: deadline_yesterday + 0 trades -> disabled; deadline_tomorrow -> unchanged; deadline_past + 1 trade -> unchanged
6. Safety: only applies when trades_lifetime==0
- [ ] [2026-05-28] **Blokada boostów size_multiplier gdy SPY RSI > 70 (overbought)** _(risk: low, effort: ?, revisit: no specific date)_
  - **Rationale:** SPY RSI 71.5 (2026-05-28) = overbought. Backtest pokazał że momentum-long ma najlepszy edge przy RSI 50-65; wejście przy RSI >70 kupuje na szczycie. Heurystyka blokuje auto-boost size_multiplier dla strategii momentum gdy SPY overbought — chroni przed buy-the-top i zapobiega wzmacnianiu pozycji na przegrzanym rynku.
- [x] [2026-05-28] **Zombie-prune carve-out: nie prune gdy RSI ekstremalny dla powiązanego instrumentu** _(risk: medium, effort: 2-3h, revisit: 2026-06-04)_ — **CLOSED 2026-05-30 v3.11.3 part 3: superseded by LLM-lock (14 dni). Crypto-oversold-bounce path też shipped.**
  - **Rationale:** Auto-prune (21 dni, 0 trade'ów) wyłączyła crypto-momentum gdy BTC/ETH RSI ~20 — najgorszy możliwy moment. Prune powinna być zawieszona gdy rsi_snapshot wskazuje ekstremalne odczyty dla instrumentów powiązanych ze strategią. Wymaga modyfikacji zombie_prune_stale_strategies() + safe_apply_overrides() — wieloplikowa zmiana, poza zakresem auto_pr.
  - **Sketch:** W adapter.py::zombie_prune_stale_strategies(name, strategy_state, stats):
  CRYPTO_STRATEGIES = {'crypto-momentum', 'crypto-breakdown'}
  rsi = stats.get('rsi_snapshot', {})
  btc_rsi = rsi.get('BTC/USD', {}).get('today', 50)
  eth_rsi = rsi.get('ETH/USD', {}).get('today', 50)
  if name in CRYPTO_STRATEGIES and (btc_rsi <= 25 or eth_rsi <= 25):
    return None, f'PRUNE SKIPPED: extreme crypto RSI BTC={btc_rsi} ETH={eth_rsi}'
W safe_apply_overrides(): gdy LLM override sets enabled=True + state has hard_safety=True:
  → clear hard_safety + auto_pruned_at before applying
Files: learning-loop/adapter.py
- [x] [2026-05-28] **Fill-rate attribution: mapowanie 'unknown' orderów do strategii via symbol** _(risk: low, effort: 1h, revisit: 2026-06-04)_ — **CLOSED 2026-05-30 v3.11.3 part 3 SHIPPED: SYMBOL_STRATEGY_MAP w analyzer._strategy_from_client_id. XOM→geo-xom, CVX→geo-energy, RTX/LMT→geo-defense, GLD→geo-gold.**
  - **Rationale:** fill_rate['unknown'] skupia 19 zleceń bez attributii (37% fill rate; CVX/XOM/TSLA jako open GTC). Bez attributii nie widać który monitor ma problem. Symbol-based fallback (XOM→geo-xom, CVX→geo-energy, TSLA→price-momentum-long) ujawni rzeczywiste fill-rate per strategia i pozwoli targetować poprawki limitów.
  - **Sketch:** W analyzer.py::compute_fill_rate():
  SYMBOL_STRATEGY_MAP = {'XOM': 'geo-xom', 'CVX': 'geo-energy', 'GLD': 'geo-gold',
    'TSLA': 'price-momentum-long', 'AAPL': 'price-momentum-long', ...}
  Dla orderów gdzie client_order_id nie ma known prefiksu strategii:
    → sprawdź symbol w mapie → bucket = SYMBOL_STRATEGY_MAP.get(symbol, 'unattributed')
  Zmień klucz 'unknown' na 'unattributed' dla przejrzystości
  Files: learning-loop/analyzer.py
- [x] [2026-05-29] **Zombie-prune LLM lock: block auto-prune for 14 days after explicit LLM override** _(risk: medium, effort: 2-3h, revisit: 2026-06-05)_ — **CLOSED 2026-05-30 v3.11.3 part 3 SHIPPED: cfg['last_llm_override_at'] stamped in safe_apply_overrides; _flag_silent_strategies honors 14-day lock. 5 unit tests.**
  - **Rationale:** Nieskończona pętla: LLM re-enableuje crypto-momentum → następny run zombie-prune re-disabla z hard_safety=True → LLM re-enableuje (cykl się powtarza). Policy powinna respektować aktywny LLM override przez 14 dni — inaczej każda noc deterministic adapter cofanie zmian które LLM celowo wprowadził.
  - **Sketch:** 1. W analyzer.py::apply_llm_overrides(): dla każdej strategii zmienionej przez LLM: state[name]['last_llm_override_at'] = today_iso
2. W adapter.py::auto_prune_zombies() (lub equivalent): if state.get(name,{}).get('last_llm_override_at') and (today - parse(last_llm_override_at)).days < 14: skip; log 'zombie-prune SKIPPED: active LLM override expires <date>'
3. W state.json schema: last_llm_override_at per strategy string field
4. Grace period: 14 dni daje LLM czas zebrać dane zanim prune wróci
- [x] [2026-05-29] **fill_rate open-orders correction: separate OPEN-GTC from UNFILLED-REJECTED** _(risk: low, effort: 1h, revisit: 2026-06-01)_ — **CLOSED 2026-05-30 v3.11.3 part 3 SHIPPED: compute_fill_rate emits fill_rate_closed = filled/(filled+canceled+expired+rejected); alert path uses _closed, skips when closed_total=0. 4 unit tests.**
  - **Rationale:** fill_rate.unknown = 37% (12/19 'other' = open GTC orders) generuje fałszywy alert 'limits too tight' gdy faktycznie zlecenia czekają na rynek (open_status_new=5). Precyzyjna metryka: fill_rate_closed = filled/(filled+canceled+expired+rejected), ignorując open orders.
  - **Sketch:** W analyzer.py::compute_fill_rate(): fill_rate_closed = filled / max(1, filled+canceled+expired+manually_canceled+rejected); open_pending = open_status_new + open_status_held; emituj fill-rate-alert tylko gdy fill_rate_closed < 0.5 (open pending nie liczy się do alertu); dodaj 'open_pending' do output dla diagnostyki. Eliminuje fałszywe alerty dla GTC order setups.

---

## v3.13.x — System-readiness gaps (added 2026-05-30 after v3.13.1)

These four items are **known gaps in operational readiness** — system
works without them but each blocks one dimension of full autonomy or
trustworthy edge measurement. Tracked here so operator/future-Claude
implements them at the right moment. Auto-surfaced in
`scripts/session_report.py::derive_risk_flags` as `🟡` info badges so
they appear daily until resolved.

## v3.15.0 shipped 2026-06-04 — trader feedback batch (10 modules + 56 tests)

Closed via v3.15.0: FB-001 InstrumentProfile, FB-003 LeadLagAnalyzer,
FB-004 DynamicInstrumentProfiler, FB-005 StrategyRegistry, FB-006 SourceQualityPolicy,
FB-011 PositionManager (module + tests; exit-monitor wiring v3.16),
FB-012 LiquiditySweepGuard, FB-013 SessionEffectivenessMonitor,
FB-014 Tier 3 social-source cap, FB-015 DD-not-day-trade-trigger rule.

Interface-only (data/operator decision needed): FB-002 pre-open behavior,
FB-007/008 event-monitor interface + MockDOJMonitor, FB-010 universe abstraction.

Already covered: FB-009 defense monitor.

Documentation: `docs/feedback_requirements.md`, `docs/feedback_implementation_v3150.md`,
6 module-specific docs in `docs/`.

## v3.15.x backlog (after trader-feedback batch)

- [ ] [2026-06-04] **v3.14.1 — Heartbeat wiring infra fix** _(P0, 30 min, revisit asap)_
  - Wire `permissions: contents: write` + commit step into 5 workflow YAMLs:
    `defense-monitor.yml`, `twitter-monitor.yml`, `geo-monitor.yml`,
    `options-monitor.yml`, `price-monitor.yml`.
  - Heartbeat code is correct (v3.14.0) but runtime_state.json writes don't
    reach origin → heartbeat shows 5/11 instead of 11/11.
- [ ] [2026-06-04] **v3.14.1 — PDT cooldown persist** _(P0, 1h)_
  - `exit-monitor._PDT_BLOCK_COOLDOWN: dict = {}` is module-level state.
    Resets every cron tick. Persist to `runtime_state.json::pdt_cooldown`.
- [ ] [2026-06-04] **v3.16 — Wire position_manager into exit-monitor** _(P1, 2-3h)_
  - Persist `PositionState` per symbol in `runtime_state.json::positions`.
  - `exit-monitor.run_exit_check` calls `evaluate_position()` per pos.
  - Audit `LIFECYCLE_TRANSITION` events.
- [ ] [2026-06-04] **v3.16 — Wire session_effectiveness into monitors** _(P1, 2h)_
  - Each monitor + risk gate emits matching `EVT_*` event.
  - New workflow `session-effectiveness-check.yml` every 15 min: report +
    safe_mode trigger on degradation.
- [ ] [2026-06-04] **v3.16 — Wire instrument_profile + liquidity_sweep into 3 monitors** _(P1, 2h)_
  - crypto/price/options-monitor build `instrument_profile` via DynamicProfiler.
  - Pass profile + recent bars to `liquidity_sweep_guard.evaluate_sweep_risk`.
  - Both flow into `confidence_inputs`.
- [ ] [2026-06-04] **v3.16 — Wire source_quality into news monitors** _(P1, 1h)_
  - defense / twitter / reddit / politician / geo monitors classify their
    `source_type` and pass through `confidence_inputs.source_type`.
- [ ] [2026-06-04] **v3.17 — Pre-open behavior real data source** _(P2, operator decision)_
  - Operator decides: brokerage pre-market export OR another free source.
  - Module ships with synthetic-data tests; ready to wire when source picked.
- [ ] [2026-06-04] **v3.17 — Hourly crypto-bar backtest harness** _(P2, 3-4h)_
  - Add hourly bar fetcher to `backtest/data.py`.
  - Port `check_crypto_signal` to `backtest/strategies.py::crypto_momentum_signal_at`.
  - Backtest crypto-momentum + crypto-oversold-bounce over 6 months.
  - Required before flipping EDGE_GATE_ENABLED=true.
- [ ] [2026-06-04] **v3.17 — Event-driven backtest harness** _(P2, 4-6h)_
  - Historical news event replay for geo-defense/-energy/-gold.
  - Build minimal event-stream + replay loop.

## v3.15 scope from audit-board 2026-06-02 (pre-existing)

These items remained P1/P2 after v3.14.0 closed Themes A (confidence gate
activation + heartbeat completion) and the DOC-003 strategy doc. They will
be addressed in the next iteration.

- [ ] [2026-06-02] **STRAT-001: geo-defense empirical loss — 20 trades / 20% WR / -$44 over 7 days** _(risk: medium, effort: 30 min review + decision, revisit: after 30+ closed geo-defense trades or 2026-06-15 whichever earlier)_
  - **Rationale:** Audit-board 02 (trading_strategy_reviewer 2026-06-02) flagged geo-defense as the only strategy with empirically poor edge in production data. v3.13.3 P1-2 mitigates (recent-loss cooldown skips BUY after 5-loss streak) but does not address underlying setup quality.
  - **Action:** if WR stays < 35% after 30 closed trades, disable strategy in `state.json` with documented rationale OR refine signal (require stronger event scoring threshold).
  - **Watch:** `learning-loop/history/<date>.md::strategies.geo-defense.win_rate` aggregated 14-day rolling.

- [ ] [2026-06-02] **STRAT-002: 14-day observation window for crypto-oversold-bounce** _(risk: low, effort: passive, revisit: 2026-06-16)_
  - **Rationale:** v3.13.3 relaxed entry condition (strict 1-bar reversal → 3-bar stabilization + 25% vol floor). v3.14.0 wired confidence_inputs. Strategy still has 0 lifetime trades as of 2026-06-02. Observation window: if still 0 fires by 2026-06-16 despite BTC/ETH RSI dipping below 30, classify as PIPELINE_FAILURE not no_edge → either further relax OR disable.
  - **Watch:** `state.json::strategies.crypto-oversold-bounce.placed_lifetime` and per-session log "OVERSOLD-BOUNCE" lines from crypto-monitor.
  - **Note:** strategy now has documentation in `strategies/crypto-oversold-bounce.md` (DOC-003 closed).

- [ ] [2026-06-02] **STRAT-003: EDGE_GATE_DISABLED still default — strategies enable without backtest gate** _(risk: medium, effort: 3-4h backtest matrix + decision, revisit: 2026-06-15)_
  - **Rationale:** Per audit-board finding STRAT-003. `learning-loop/edge_validator.py` ships v3.11 with WR≥50%/PF≥1.3/MDD<20%/n≥10 gate but operator opt-in deferred. Cross-ref READINESS-2.
  - **Action:** run `python -m backtest.run --strategy <each> --mode both --walk-forward 3` for all 9 enabled strategies. For passing strategies, flip `EDGE_GATE_DISABLED=false` in `daily-learning.yml`. For failing, document `paused_until` in state.json with rationale.

- [ ] [2026-06-02] **RISK-002: SL -5% might be too tight — 4 SL bracket hits same day on 2026-06-01** _(risk: medium, effort: 2h backtest comparison, revisit: 2026-06-15)_
  - **Rationale:** Audit-board 03 (risk_reviewer) flagged. ORCL/WDAY/QQQ/GLD hit SL on 2026-06-01 day-of-entry → -$1,600 realized. May indicate -5% SL is inside normal intraday volatility range. Could be regime-specific (NEUTRAL regime needs wider SL than RISK_ON).
  - **Action:** backtest `--mode both` with SL=-5% baseline vs SL=-7% variant across last 6 months on all enabled stocks. If -7% shows materially fewer SL hits + comparable WR + better P&L → migrate via `config/aggressive_profile.json::exits.stocks_etf.sl_pct`. Regime-conditional SL also worth exploring.

- [ ] [2026-06-02] **SIMP-001: MonitorBase extraction — 11 monitors duplicate ~50 LOC boilerplate** _(risk: low, effort: 4-6h refactor + test migration, revisit: opportunistic — bundle with future feature touching all monitors)_
  - **Rationale:** Audit-board 09 (simplicity_refactoring) flagged. Each monitor repeats VIX guard + drawdown_guard + concentration_ok + has_open_position + notify_signal + heartbeat ping plumbing. When pattern evolves (e.g. add confidence_inputs), 11 edit sites. Real cause of CONF-002 dormancy v3.13 → v3.14.0.
  - **Sketch:** extract `shared/monitor_base.py::MonitorBase` with `pre_signal_gates(symbol, side, size_usd) → (ok, reason)` and `emit_signal(signal_dict)`. Add `confidence_inputs` builder hook. Each monitor inherits.
  - **Defer:** v3.14.0 ships confidence_inputs without MonitorBase by adding inline at each monitor. Refactor opportunistically when next feature touches all 11.

## v3.14.0 closed batch (2026-06-02 — audit-board Themes A + B)

- [x] [2026-06-02] **CONF-002: confidence gate DORMANT in production** ✅ DONE v3.14.0 — `confidence_inputs` now populated by crypto-monitor (Phase 3 emit loop), price-monitor (`_attach_ci` in LONG/SHORT/LEVERAGED), options-monitor (inline gate in `execute_proposal`). `shared/alpaca_orders.py::place_stock_bracket/place_crypto_order/place_simple_buy` accept new param and forward to risk_officer (stocks/crypto) or inline `_confidence_gate` (options).
- [x] [2026-06-02] **DATA-002: monitors don't emit confidence_inputs** ✅ DONE v3.14.0 — same as CONF-002 (cross-ref). New `shared/confidence_builder.py` DRY helper builds dict from common context.
- [x] [2026-06-02] **TEST-002: no production-level integration test for confidence_inputs** ✅ DONE v3.14.0 — new `tests/test_confidence_wired_v3140.py` 13 tests including TestConfidenceBuilderDirect (4) + TestRiskOfficerHonorsConfidenceInputs (3) + TestAlpacaOrdersAcceptsConfidenceInputs (5) + TestHeartbeatExpansion (1 AST scan).
- [x] [2026-06-02] **ARCH-001 / RUNTIME-002 / CONF-003: heartbeat partial 4/11** ✅ DONE v3.14.0 — 8 monitors wired (defense/twitter/reddit/geo/politician/options/options-exit/price). Heartbeat 11/11 EXPECTED_COMPONENTS. `score_system_health` returns true ratio.
- [x] [2026-06-02] **DOC-003: crypto-oversold-bounce undocumented** ✅ DONE v3.14.0 — new `strategies/crypto-oversold-bounce.md` (~160 lines) with market hypothesis, entry/exit conditions, risk guards stack, empirical state, do-not-trade conditions.

- [x] [2026-05-30] **READINESS-1: Heartbeat module not wired into the 11 monitors** _(closed 2026-06-02 v3.14.0 — all 11/11 monitors now ping `heartbeat.ping("<component>")` at end of __main__: v3.13.3 wired crypto/exit/incident/allocator; v3.14.0 wired defense/twitter/reddit/geo/politician/options/options-exit/price. `confidence.score_system_health` returns true ratio. New `TestHeartbeatExpansion` regression test in `tests/test_confidence_wired_v3140.py` AST-scans all 8 v3.14.0 files. Session-report risk_flags will flip 🟡→🟢 on next session run.)_
  - **Rationale:** `shared/heartbeat.py` shipped v3.12.0 as a library + tests, but no monitor calls `heartbeat.ping(name)` after a successful run yet. Result: `learning-loop/runtime_state.json::heartbeat` is empty → `confidence.score_system_health` cannot compute `components_alive` and falls back to neutral 0.5. One of 5 confidence components is "blind". System still safe (Cloudflare Worker firing + GH cron success/failure gives external pulse), but confidence-score readiness stays `partial`.
  - **When to implement:** as soon as a single full session (Mon 2026-06-01) confirms cron + monitor pipeline is healthy end-to-end. Low-risk surgical edit.
  - **Sketch:**
    1. Each of 11 monitors (`crypto-monitor/`, `defense-monitor/`, `geo-monitor/`, `twitter-monitor/`, `reddit-monitor/`, `politician-monitor/`, `price-monitor/`, `options-monitor/`, `options-exit-monitor/`, `exit-monitor/`, `scripts/incident_pattern_detector.py`) needs ~3 LOC at the very end of `run_scan()` / equivalent:
       ```python
       try:
           sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
           from heartbeat import ping
           ping("<monitor-name>", status="ok", message=f"scanned {n} symbols")
       except Exception:
           pass  # fail-soft: don't crash monitor if heartbeat write fails
       ```
    2. Each workflow YAML needs `contents: write` permission + commit step for `learning-loop/runtime_state.json` (uses same retry-on-non-fast-forward pattern as existing exit-monitor).
    3. After deploy, verify `cat learning-loop/runtime_state.json | jq '.heartbeat | keys'` returns ~11 components within 15 min.
    4. Re-check `confidence.system_health` component — should now be > 0.9 in healthy session.
  - **How operator notices:** `scripts/session_report.py` heartbeat section will show `Alive (0)` until wired; afterwards should show `Alive (10-11)`. Auto-flagged as 🟡 in risk_flags while gap persists.
  - **Files:** all 11 monitor .py + their workflow YAML templates in `scripts/workflow-templates/` + `.github/workflows/*.yml` (via sync-workflows).
  - **Tests:** new `tests/test_heartbeat_wired.py` — for each monitor, AST-scan that imports `heartbeat` and calls `ping(...)`.
  - **Definition of done:** `confidence.score_system_health(components_alive=11, components_total=11, ...) > 0.9` reproducibly in production audit JSONL events.

- [ ] [2026-05-30] **READINESS-2: EDGE_GATE_DISABLED env still defaults true → no backtest-gated strategy enablement** _(risk: medium, effort: passive monitoring + backtest cycle ~3h human, revisit: 2026-06-15 OR after 30+ live paper trades)_
  - **Rationale:** `learning-loop/edge_validator.py::_is_disabled` reads `EDGE_GATE_DISABLED` env (default `"true"`). Until operator flips to `"false"` AND every enabled strategy has a passing backtest report (WR≥50%, PF≥1.3, MDD<20%, n≥10 closed trades), strategies can fire signals without statistical-edge proof. Current behavior is intentional (v3.11 "opt-in" design) but the system is silently running un-gated.
  - **When to implement:**
    - **Step A (now-ish):** run backtest for each enabled strategy. Example: `python -m backtest.run --strategy momentum-long --tickers AAPL MSFT NVDA AMD --days 180 --mode both --walk-forward 3`
    - **Step B:** if a strategy fails the thresholds, EITHER (a) refine its parameters and re-test, OR (b) disable it in `state.json` with documented `rationale`.
    - **Step C:** flip `EDGE_GATE_DISABLED=false` in `.github/workflows/daily-learning.yml::env`.
    - **Step D:** observe rationale.md for one week — does any enabled strategy get auto-disabled by `enforce_edge_gate_on_state`? If yes, that's the validator working as designed.
  - **How operator notices:** rationale.md prints `edge-gate: DISABLED via EDGE_GATE_DISABLED env` line until disabled — already suppressed from rationale daily in v3.11.3 part 3. Backlog item kept as the actionable reminder.
  - **Risk if skipped:** confidence component `signal_strength` cannot be calibrated against historical edge; strategies promoted purely on LLM sentiment may have negative real edge.
  - **Definition of done:** `EDGE_GATE_DISABLED=false` in `daily-learning.yml`, AND each enabled strategy in `state.json` has an associated `learning-loop/backtests/<strategy>_<date>.json` artifact, AND no strategy auto-disabled by edge gate over 7 days.

- [ ] [2026-05-30] **READINESS-3: No empirical edge validation — system has <30 live paper trades since v3.11.3 fix unblocked crypto pipeline** _(risk: medium, effort: passive — just observe, revisit: 2026-06-30 OR after 30 closed paper trades whichever earlier)_
  - **Rationale:** Crypto-monitor was SILENT for 45 days (2026-04-15 → 2026-05-29) due to predator-bracket filter blocking oversold-bounce setups. Fix shipped v3.11.3 part 3 (2026-05-30). Result: system has been live but barely traded. Confidence ceiling computed at ~0.93, but the ceiling is theoretical — without paper-trade history, win-rate/profit-factor/max-drawdown numbers are unknown. **Cannot claim edge exists.**
  - **When to implement:** passive — just wait 4-6 weeks. After 30+ closed trades (mix of all enabled strategies), analyzer's per-strategy stats become statistically meaningful (small but non-zero sample). Daily-learning Senior PM can then offer evidence-based recommendations.
  - **Metric to track:**
    - `learning-loop/history/<date>.md::cumulative_trades` should rise past 30
    - `learning-loop/state.json::strategies.*.trades_lifetime` aggregated
    - Per-strategy: WR > 50% AND PF > 1.3 over ≥10 closed trades
  - **What to do at milestone:** generate edge-validation report via:
    ```
    python -m backtest.run --strategy <each> --mode both --walk-forward 3
    diff backtest results vs live paper results
    ```
    If live underperforms backtest by > 50%, investigate (regime mismatch, slippage, sample bias).
  - **Definition of done:** at least 30 closed paper trades total, with at least 2 strategies showing WR ≥ 50% AND PF ≥ 1.3 over their individual histories, AND no `[INCIDENT-CRITICAL]` over preceding 14 days.
  - **Until then:** operator must NOT scale capital, must NOT touch `kill_switch_armed`, must NOT recommend live trading.

- [x] [2026-05-30] **READINESS-4: Multi-Agent Audit Board has never been executed — board structurally ready but zero review-cycles done** _(closed 2026-06-02 — first board cycle complete; final_decision_2026-06-02.md = APPROVE_PAPER_TRADING_WITH_WARNINGS + NOT_SAFE_FOR_LIVE_TRADING; 11 area reports + Final Arbiter all validated by `run_agent_board.py validate-reports`. v3.14 scope identified: CONF-002 + DATA-002 + TEST-002 batch (confidence_inputs wiring) + ARCH-001 batch (heartbeat 7/11 remaining) + DOC-003 (crypto-oversold-bounce strategy doc). Next cycle target: after v3.14 ships OR 7-14 days.)_
  - **Rationale:** `agents/` ships v3.13.0 with 13 prompts + 3 schemas + runner + 28 green structural tests. But no actual review cycle has been run — no `agents/reports/01_architecture_reviewer_2026-XX-XX.md` exists. Without a Final Arbiter decision on file, operator has no formal "fit to paper trade" verdict from the full multi-agent perspective.
  - **When to implement:**
    1. **First baseline run:** within 7 days (target: 2026-06-07 weekend). Operator runs `python3 agents/run_agent_board.py init <date>`, then walks through each of 11 area-agent prompts (either with LLM session OR manually), produces 11 area reports, runs Final Arbiter prompt 12 to produce binding decision.
    2. **Weekly cadence after baseline:** every Sunday before next week's trading.
    3. **Before any capital escalation:** never escalate position size, kill-switch state, or live-readiness without a fresh Final Arbiter decision ≤7 days old.
  - **How operator notices:** session_report's readiness section will show 🟡 "Audit Board last run: never" until at least one Final Arbiter decision exists in `agents/reports/`.
  - **Cost:** $0 (uses local runner + operator's existing LLM tool of choice).
  - **Definition of done:** at least one full board cycle complete (11 area reports + 1 Final Arbiter decision), Final Arbiter decision ≤ 7 days old, decision is one of {APPROVE_LOCAL_REPLAY, APPROVE_PAPER_TRADING_WITH_WARNINGS} (NOT one of the BLOCK_* / NEEDS_* set), AND the decision is recorded in `agents/reports/final_decision_<date>.md` conforming to `agents/schemas/final_decision.schema.json`.
- [ ] [2026-05-30] **Crypto pipeline diagnostic — auto-flag gdy RSI <30 przez ≥3 dni ale 0 placements** _(risk: low, effort: 2-3h, revisit: 2026-06-01)_
  - **Rationale:** BTC/ETH RSI <30 przez 4+ dni z rzędu, ale crypto-momentum i crypto-oversold-bounce mają placed_lifetime=0. System nie potrafi sam wskazać gdzie pipeline się urywa: generowanie sygnału, quote fetch, order placement, czy odpowiedź Alpaca. Diagnostic alert eliminowałby ten blind spot.
  - **Sketch:** W crypto-monitor/monitor.py: jeśli RSI ≤30 przez ≥3 ticki (state.json::crypto_state.oversold_streak), a żaden BUY nie został złożony w ostatnich 24h → emit notify_diagnostic() z: (a) ostatnim fetch URL + HTTP response code z get_daily_bars(), (b) wynikiem place_simple_buy z dry_run=True (pokazuje czy parametry są poprawne), (c) account buying_power vs size_usd. Trigger: cron-tick gdzie oversold_streak >= 3 AND last_placed_at older than 24h. Files: crypto-monitor/monitor.py (oversold_streak counter w state), shared/notify.py (notify_diagnostic nowa funkcja). Effort: ~2h.
- [ ] [2026-05-30] **Equity gap reconciliation — gdy delta >$500 AND no_positions AND no_trades** _(risk: low, effort: 1h, revisit: 2026-06-01)_
  - **Rationale:** Dziś equity_gap WARN: -$1,106 z jednoczesnym 0 otwartych pozycji i 0 trade'ów. Ta kombinacja jest analitycznie niemożliwa bez ukrytego exposure lub API bug. Systemowy reconciliation eliminowałby ślepy punkt i dałby LLM konkretne dane zamiast spekulacji.
  - **Sketch:** W learning-loop/analyzer.py::compute_equity_gap_alert: jeśli severity in [WARN, ERROR] AND open_positions==[] AND cumulative_trades==0 → dodaj pole 'reconciliation_needed': True + pobierz /v2/orders?status=all&after=<24h_ago>&limit=50 → znajdź fills z side='sell'/'buy_to_close' które nie mają pary w state attribution → surfacuj jako 'unattributed_fills' list. Files: learning-loop/analyzer.py, shared/alpaca_orders.py (get_recent_orders helper). Effort: ~1h.
- [ ] [2026-06-07] **CRITICAL alert gdy BTC RSI <15 przez 3 kolejne uruchomienia i 0 crypto trades placed** _(risk: low, effort: 1h, revisit: 2026-06-10)_
  - **Rationale:** 63 dni ciszy na crypto-momentum z BTC RSI poniżej 15 przez kilka dni z rzędu = pipeline uszkodzony, nie brak edge. Automatyczny alert spowoduje interwencję operatora zanim zmarnujemy kolejny potencjalny setup wartości kilku tysięcy dolarów.
  - **Sketch:** W analyzer.py::compute_rsi_snapshot() dodać check: jeśli BTC RSI <15 I crypto-momentum.trades_7d == 0 I crypto-oversold-bounce.trades_7d == 0, sprawdzić run_count dla crypto-monitor z monitor-health/latest.json. Jeśli run_count >10 w 24h → emit new alert 'CRYPTO_PIPELINE_CRITICAL' z severity=CRITICAL w today_stats. Wired do notify.py z subject [CRITICAL] Crypto pipeline silent during RSI emergency. Pliki: learning-loop/analyzer.py (+20 LOC), shared/notify.py (+10 LOC), learning-loop/health/latest.json (read only).
- [ ] [2026-06-07] **Persistent equity gap: escalate po 3 kolejnych WARN dniach z 0 attributed trades** _(risk: low, effort: 1h, revisit: 2026-06-14)_
  - **Rationale:** Equity spada $8,624 przez kilka dni z 0 atrybucją — po 3 dniach z rzędu takiego wzorca operator powinien dostać CRITICAL, nie kolejny WARN. Obecny system emituje WARN co dzień bez eskalacji, co powoduje alert fatigue i brak reakcji.
  - **Sketch:** W state.json dodać 'equity_gap_consecutive_days': int (reset gdy severity != WARN lub delta_usd > -1000). W analyzer.py::compute_equity_gap_alert() inkrementować counter, jeśli >= 3 zmieniać severity na CRITICAL i email subject na [CRITICAL-EQUITY-GAP]. Pliki: learning-loop/analyzer.py (+15 LOC), learning-loop/state.json (nowe pole), shared/notify.py (+5 LOC).
