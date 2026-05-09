# Heuristic Proposals (LLM-generated)

> Open queue of heuristic ideas suggested by the daily LLM
> annotator + weekly retrospective. Tick the box `[x]` when
> implemented in `learning-loop/adapter.py`. Older entries
> kept indefinitely so we can audit which ideas worked.

- [ ] [2026-05-07] Emergency exit orders (exit-emergency-*) muszą używać MARKET order — limit na emergency exit = ryzyko braku wypełnienia w panice. Fix: w exit-monitor i options-exit-monitor ustaw type=market dla zleceń oznaczonych jako emergency (rationale: exit-emergency-googl fill_rate=0 w tej sesji).
- [ ] [2026-05-07] TP orders niefilled przez całą sesję (exit-tp-qqq699) wskazują na zbyt agresywny TP względem bieżącej ceny — rozważ trailing stop dla pozycji trzymanych >12h zamiast statycznego TP (testable: porównaj hold_time vs TP-hit-rate po 10 dniach danych).
- [ ] [2026-05-07] analyzer.py musi mapować client_order_id do nazwy strategii — bez tej atrybucji cumulative_trades=0 i LLM nie może ocenić krawędzi. Sprawdź schemat nazewnictwa: czy monitor ustawia client_order_id z prefiksem strategii przy zleceniu bracket? Jeśli nie — dodaj (priorytet: bloker dla całego learning loop).

<!-- ============================================================ -->
<!-- 2026-05-08 daily LLM output (rescued manually — routine push  -->
<!-- to main was blocked 403 by proxy; rescued from feature branch -->
<!-- claude/adoring-maxwell-YLZLC and applied here). Architectural -->
<!-- channel fix tracked separately in CLAUDE.md backlog.          -->
<!-- ============================================================ -->

- [ ] [2026-05-08] **PILNE: exit-emergency 0/4 filled — zbadać typ zlecenia i przełączyć na MARKET** _(risk: high, effort: 1h, revisit: 2026-05-09)_
  - **Rationale:** 4 exit-emergency orders placed today, 0 filled (0%). Emergency exits are the last defense line — unfilled emergency exits mean we hold full loss through tail events. Must investigate immediately: is exit-emergency using LIMIT or MARKET? If LIMIT, the price is chasing a fast market and will never fill in the conditions that trigger emergency exit.
  - **Status (2026-05-09):** ✅ FIXED in commit (this session) — exit-monitor now places emergency closes directly via Alpaca REST with `type=market`, bypassing the routine. client_order_id tagged `exit-emergency-{symbol}-{ts}` for clean attribution.
- [ ] [2026-05-08] **options fill rate cap — auto-reduce size_multiplier when fills < 50%** _(risk: low, effort: auto-PR, lane=auto_pr)_
  - **Rationale:** options-momentum fill_rate=40% (4/10) today. Placing 10 phantom orders wastes allocated capital and creates ghost signal noise. Auto-capping size_multiplier at 0.60 when fill rate < 50% over >= 5 placed orders forces the system to deploy less notional until execution improves.
  - **Status:** queued for Lane 2 auto-PR — would have been auto-opened if routine could push to main; deferred until channel fix lands.
- [ ] [2026-05-08] **PILNE: analyzer nie atrybuje zleceń — by_strategy puste 3 dzień z rzędu** _(risk: high, effort: 1h, revisit: 2026-05-09)_
  - **Rationale:** by_strategy is empty for the third consecutive day despite the _is_close fix from 2026-05-07. Without strategy attribution, neither the adapter nor the LLM can assess per-strategy edge. The entire learning loop is flying blind.
  - **Sketch:** `reconstruct_trades` only matches client_order_ids that appear in BOTH an open and close within the 24h window — if positions are held across days, reconstruct_trades finds 0 round-trips. Fix: also attribute single-leg orders (entries without matching close) to their strategy for partial stats. Alternative: add a 'by_order_prefix' attribution path that extracts strategy name from client_order_id prefix directly.
- [ ] [2026-05-09] **Detect high-cancel-rate strategies and recommend size scaling (fill-rate guard)** _(risk: low, effort: ?, revisit: no specific date)_
  - **Rationale:** options-momentum averaging 40% fill rate (3+ canceled per 10 placed, 3 consecutive days). New standalone function returns (should_cut, factor, reason) when cancel_rate >= 50% — operator wires into analyze() as additional pass before state.json write.
- [ ] [2026-05-09] **Detect chronic options-momentum fill deficit (< 50% on >= 5 placed orders)** _(risk: low, effort: ?, revisit: no specific date)_
  - **Rationale:** options-momentum osiągnął 40% fill rate przy 10 placed — trzeci dzień z rzędu nie wchodzimy w 60% zamierzonych pozycji przez ciasne limity. Funkcja diagnostyczna wyemituje WARNING do rationale gdy stan się utrzymuje, dając operatorowi jasny sygnał do korekty limit-price logiki w options-monitor.
- [ ] [2026-05-09] **options-exit: accelerated close for near-expiry positions (DTE <= 5) with loss > 40%** _(risk: low, effort: 1h, revisit: 2026-05-14)_
  - **Rationale:** QQQ260514P00699 ma -62% straty z DTE ~5 — theta decay przyspiesza nieliniowo poniżej 5 DTE i statyczny SL=entry*0.50 jest za wolny. Wcześniejszy trigger dla near-expiry pozycji zapobiegłby dalszemu bleeding na opcjach wygasających w tym tygodniu.
  - **Sketch:** W options-exit-monitor/monitor.py: przy ewaluacji każdej pozycji, wyciągnij expiry date z OCC symbol (format: TICKER + YYMMDD + C/P + strike*1000). Oblicz DTE = (expiry_date - today).days. Jeśli DTE <= 5 AND current_price < entry_price * 0.60 → fire SELL MARKET (nie LIMIT — near-expiry opcje mają szerokie spready, LIMIT może nie wejść w czasie). Tag client_order_id: 'exit-neardth-{symbol}-{ts}'. Progi: DTE <= 5 + loss > 40% (liberalniej niż normalny SL=50% bo theta decay przyspiesza nieliniowo). Test: OCC=QQQ260514P00699, DTE=4, P&L=-62% → trigger; DTE=15, P&L=-62% → HOLD (normalny SL wystarczy).
- [ ] [2026-05-09] **options-monitor: use bid/ask midpoint + 5% margin as limit price instead of close_price** _(risk: medium, effort: 1h, revisit: 2026-05-14)_
  - **Rationale:** 40% fill rate opcyjny to systematyczny problem — close_price z /v2/options/contracts jest staroświeckie i nie odzwierciedla realnego bid/ask spreadu (który w opcjach wynosi 5-20% nominal). Użycie midpoint * 1.05 jako agresywnego limitu powinno poprawić fill rate z 40% do 70%+.
  - **Sketch:** W options-monitor/monitor.py: w execute_options_buy(), po wyborze kontraktu, dodaj call do Alpaca /v2/options/snapshots/{symbol}. Pobierz bid_price i ask_price. limit_price = (bid + ask) / 2 * 1.05. Fallback na close_price * 1.05 jeśli snapshot call fails (network error, brak quote). Dodatkowy koszt: 1 Alpaca API call per contract attempt. Weryfikacja: mock snapshot z bid=4.00/ask=4.40 → limit=4.41 vs obecne close=4.35. Oczekiwany efekt na fill rate: ~+30 pp (40% → 70%). Uwaga: midpoint * 1.05 to buyer-aggressive limit — płacimy ~2.5% ponad mid, ale dostajemy ekspozycję.
