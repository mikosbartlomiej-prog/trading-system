# Heuristic Proposals (LLM-generated)

> Open queue of heuristic ideas suggested by the daily LLM
> annotator + weekly retrospective. Tick the box `[x]` when
> implemented in `learning-loop/adapter.py`. Older entries
> kept indefinitely so we can audit which ideas worked.

- [ ] [2026-05-07] Emergency exit orders (exit-emergency-*) muszą używać MARKET order — limit na emergency exit = ryzyko braku wypełnienia w panice. Fix: w exit-monitor i options-exit-monitor ustaw type=market dla zleceń oznaczonych jako emergency (rationale: exit-emergency-googl fill_rate=0 w tej sesji).
- [ ] [2026-05-07] TP orders niefilled przez całą sesję (exit-tp-qqq699) wskazują na zbyt agresywny TP względem bieżącej ceny — rozważ trailing stop dla pozycji trzymanych >12h zamiast statycznego TP (testable: porównaj hold_time vs TP-hit-rate po 10 dniach danych).
- [ ] [2026-05-07] analyzer.py musi mapować client_order_id do nazwy strategii — bez tej atrybucji cumulative_trades=0 i LLM nie może ocenić krawędzi. Sprawdź schemat nazewnictwa: czy monitor ustawia client_order_id z prefiksem strategii przy zleceniu bracket? Jeśli nie — dodaj (priorytet: bloker dla całego learning loop).
