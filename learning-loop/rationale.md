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

