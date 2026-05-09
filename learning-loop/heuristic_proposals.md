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
