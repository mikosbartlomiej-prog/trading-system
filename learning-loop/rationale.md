# Learning Loop — Rationale Log

> **Purpose:** append-only narrative of every parameter change the learning
> loop has ever made. New entries pinned at the top. Older entries
> preserved indefinitely so future Claude (or you, the user) can audit
> "why is `options-momentum` size_multiplier set to 0.5 right now?" by
> scrolling.
>
> Each entry: date · subject · trigger · old → new · brief rationale.

---

*No entries yet — daily-learning workflow has not yet run.*
- 2026-05-07 · LLM[low] regime=unclear: Pierwszy dzień śledzenia — analyzer.py nie dopasował żadnego zlecenia do strategii (cumulative_trades=0, by_strategy pusty). Dzienny P&L -$163.57 (-0.16%) to poziom szumu, nie problem. Krytyczny sygnał: exit-emergency-googl ma fill_rate=0 — emergency exit który się nie wypełnił to luka w risk management; w prawdziwej panice siedzimy z pełną stratą. Dodatkowo exit-tp-qqq699 nie wypełniony przez całą sesję — TP zbyt daleki od ceny lub QQQ nie dobił do poziomu.
-   · global_overrides.options_side_bias: None -> None
- 2026-05-07 · LLM edge: Za mało danych — dzień 1 bez atrybutu strategii, zero obserwacji per-strategy win rate lub P&L. Jedyne obserwowalne: 83% fill rate (15/18), ale 2 z 3 niesprawnych zleceń to egzity (jeden emergency). Żadnej krawędzi nie można ocenić; wróć po min. 5 dniach z danymi.
- 2026-05-07 · no parameter changes (all strategies within thresholds)

- 2026-05-07 · LLM unavailable (skipped) — deterministic adapter only
- 2026-05-07 · no parameter changes (all strategies within thresholds)

- 2026-05-08 · LLM unavailable (skipped) — deterministic adapter only
- 2026-05-08 · no parameter changes (all strategies within thresholds)

- 2026-05-09 · LLM[low] regime=risk_off (RESCUED MANUALLY — routine push to main blocked 403 by proxy; recovered from claude/adoring-maxwell-YLZLC): Trzeci dzień śledzenia — equity spada o -3.87% ($3,890) do $96,653. Największy jednodniowy ruch od startu systemu. Krytyczny alarm: exit-emergency 4 placed, 0 filled — cztery zlecenia emergency exit nie wykonały się. To nie problem optymalizacyjny; to luka w risk management, która w fast-market trzyma nas z pełną stratą zamiast kontrolowanego wyjścia. options-momentum 40% fill rate (4/10 filled, 3 canceled) — limity systemowo za daleko od rynku opcji. Geo-entries działają normalnie (XOM/XLE/RTX po 100%, GLD canceled). by_strategy wciąż puste — cumulative_trades=0, analyzer nadal nie atrybuje zleceń do strategii pomimo poprawki _is_close; wymaga pilnej inspekcji.
- 2026-05-09 · LLM edge: Nie można ocenić edge per-strategy — cumulative_trades=0, by_strategy puste już trzeci dzień z rzędu. Geo-entries (3/4 filled) to jedyny segment z potwierdzoną execution quality. exit-emergency 0/4 to najpoważniejszy czerwony sygnał: jeśli emergency exits nie wykonują się w normalnych warunkach, w kryzysie będziemy całkowicie bez ochrony.
- 2026-05-09 · ACTION: exit-monitor patched — emergency closes now bypass routine and go direct to Alpaca REST as MARKET orders; client_order_id tagged exit-emergency-{symbol}-{ts} for analyzer attribution. LLM proposal #1 closed.
- 2026-05-09 · LLM[low] regime=risk_off: Trzeci z rzędu czerwony dzień — equity $96,648 (-3.87% / -$3,894). Krytyczny incident sesji: exit-emergency 0/4 fill rate w środku dnia — naprawiony tego samego dnia (direct REST MARKET, LLM proposal #1 zamknięty). options-momentum 40% fill rate (3/10 canceled) = limity systematycznie za ciasne; tracimy ~60% zamierzonej ekspozycji opcyjnej. by_strategy puste trzeci dzień z rzędu — nie błąd reconstruction, brak completed round-trips: wszystkie geo-entries otwarte, brak domkniętych par z matching client_order_id. Geo-entries XOM/XLE/RTX 100% fill = jedyny segment z potwierdzoną jakością wykonania.
-   · global_overrides.options_side_bias: None -> None
- 2026-05-09 · LLM edge: Zero danych per-strategy — brak completed trades trzeci dzień (oczekiwane przy otwartych pozycjach bez domkniętych par). Geo entries 100% fill = solidna execution quality. options-momentum 40% fill = płacimy prowizję za pozycje które nie wchodzą; wymaga korekty cen limitowych lub przejścia na market-at-open dla opcji.
- 2026-05-09 · no parameter changes (all strategies within thresholds)

- 2026-05-09 · LLM unavailable (skipped) — deterministic adapter only
- 2026-05-09 · no parameter changes (all strategies within thresholds)

- 2026-05-09 · LLM[low] regime=risk_on (rescued from orphan after race-condition timeout): Czwarty dzień śledzenia — equity $96,642 (-3.87% / -$3,900 od startu). Portfel trzyma bearish PUT pozycje w rynku który rally'uje: to jest core problem. Dwa sygnały strukturalne wymagają natychmiastowej reakcji: (1) exit-emergency 0/4 filled — przez minimum kilka godzin byliśmy bez ochrony emergency exit; patch wysłany w ciągu sesji, ale incydent się powtórzył po poprzedniej naprawie, co oznacza że fix z 2026-05-07 nie zadziałał w trybie produkcyjnym; (2) options-momentum 40% fill rate (4/10, 3 canceled) — systematycznie tracimy ~60% zamierzonej opcyjnej ekspozycji przez ciasne limity. Geo-ent
- 2026-05-09 · LLM edge: Brak danych per-strategy — cumulative_trades=0 czwarty dzień z rzędu, by_strategy puste pomimo naprawy _is_close(); brak domkniętych round-tripów bo wszystkie geo/options pozycje nadal otwarte. Jedyny potwierdzony edge: geo-entries execution quality 75% fill (3/4 XOM/XLE/RTX vs GLD canceled). Options-momentum 40% fill = płacimy slippage i opportunity cost bez pełnej ekspozycji; w obecnym rally PUT
- 2026-05-09  · global_overrides.options_side_bias: None -> long
- 2026-05-09 · ACTION: orphan pending-llm-daily.json from race-condition rescued + applied; analyzer timeout being bumped 300->480s
