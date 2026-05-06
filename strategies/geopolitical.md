# Strategia: Geopolitical Event Trading — v2.0

**Wersja:** 2.0 (2026-05-06 risk-on overhaul) — **4× sizing**
**Źródło prawdy:** `docs/STRATEGY.md` §4.5 (combined with defense)

---

## Opis
Strategia oparta na eskalacji/deeskalacji konfliktów geopolitycznych —
USA-Iran-Izrael, Bliski Wschód, decyzje administracji Trumpa, NATO.

**Cel ekspozycji:** część bucketu defense+geo (combined cap $25k, patrz `docs/STRATEGY.md` §4.5)

---

## Warunki wejścia

### Scenariusz ESKALACJA (BUY obronne/energia/złoto)
Warunki ALL:
- Alert priorytet HIGH (score >= 3)
- VIX < 60 (HALT only above)
- Rynki otwarte

| Ticker | Klasa       | Kierunek | Uzasadnienie                          |
|--------|-------------|----------|---------------------------------------|
| XLE    | Energia ETF | BUY      | Zagrożenie dostaw ropy przez Hormuz   |
| XOM    | Energia     | BUY      | Beneficjent wzrostu cen ropy          |
| CVX    | Energia     | BUY      | Beneficjent wzrostu cen ropy          |
| GLD    | Złoto       | BUY      | Safe haven przy niepewności           |
| RTX    | Obronne     | BUY      | Raytheon — systemy rakietowe          |
| LMT    | Obronne     | BUY      | Lockheed — lotnictwo wojskowe         |
| ITA    | Defense ETF | BUY      | Cały sektor obronny w jednym tickerze |

### Scenariusz DEESKALACJA
- Alert o zawieszeniu broni / porozumieniu (score >= 2 SHORT keywords)
- VIX < 35

| Ticker | Kierunek | Uzasadnienie              |
|--------|----------|---------------------------|
| QQQ    | BUY      | Risk-on po deeskalacji    |
| SPY    | BUY      | Odbicie rynku             |
| XLE    | SELL     | Spadek cen ropy           |
| GLD    | SELL     | Risk-on, mniej safe haven |

---

## Parametry zlecenia

- `size_usd`: **$6,000** (poprzednio $1,500 — 4× wzrost)
- `stop_loss`: **−5%** (poprzednio -3%)
- `take_profit`: **+12%** (poprzednio +6%)
- `order_type`: LIMIT
- `time_in_force`: DAY
- R:R = 2.4

---

## Zasady risk management

- Maksymalnie **6 pozycji defense+geo combined** jednocześnie
- Daily P&L stop: -12% → no new entries
- VIX HALT > 60
- RTX, LMT → tylko przy bezpośrednim konflikcie zbrojnym
- GLD → tylko gdy news dotyczy safe haven / ucieczki z rynku
- Geo-alert HIGH zamyka istniejące crypto LONG (cross-strategy hedge)

---

## Historia i wyniki

| Data       | Ticker | Kierunek | Wynik | Notatka |
|------------|--------|----------|-------|---------|
| 2026-05-04 | XLE    | BUY      | SKIP  | v1.0 brak strategii |
| 2026-05-05 | XOM    | BUY      | +0.7% | Trzymany, exit monitor → CLOSE_FLAT po 22h |
| —          | —      | —        | —     | v2.0 aktywne 2026-05-06 EOD |
