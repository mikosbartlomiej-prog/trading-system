# Strategia: Defense Market Trading — v2.0

**Wersja:** 2.0 (2026-05-06 risk-on overhaul) — **3× sizing, większy bucket geo**
**Źródło prawdy:** `docs/STRATEGY.md` §4.5

---

## Opis
Strategia oparta na analizie newsów z rynku zbrojeniowego: kontrakty DoD,
budżet militarny, eskalacja/deeskalacja konfliktów, programy zbrojeniowe,
NATO.

**Częstotliwość skanowania:** co 30 minut, 24/7
**Cel ekspozycji:** max **$25,000 gross** w defense+geo jednocześnie (4× v1)

---

## Monitorowane źródła

- **DoD Contracts** — defense.gov/News/Contracts/ (scraping)
- **Defense One RSS** — defenseone.com/rss/all/
- **Breaking Defense RSS** — breakingdefense.com/feed/
- **NewsAPI** — query: Lockheed OR Raytheon OR Northrop OR Boeing OR "defense contract" OR NATO OR Pentagon
- **Reuters World RSS** — feeds.reuters.com/reuters/worldNews
- **AP Top News RSS** — feeds.apnews.com/rss/apf-topnews

---

## Tickery

### US Big-5 (LONG + SHORT)
LMT, RTX, NOC, GD, BA

### US Mid-cap (LONG + SHORT)
KTOS, PLTR, AXON, LDOS, SAIC, CACI

### Defense ETFs (tylko LONG)
ITA, XAR, DFEN

### European ADRs (tylko LONG)
BAESY, EADSY

### Geo basket (energy + safe-haven)
XLE, XOM, GLD, CVX

---

## Warunki wejścia

### LONG (score >= 2 słów kluczowych, LONG dominuje nad SHORT)
- contract awarded, billion contract, awarded $
- indefinite delivery, idiq, government contract
- defense budget increase, ndaa, supplemental funding
- nato expansion, 2% gdp, rearmament
- new weapons program, hypersonic, drone program
- f-35, f-47, b-21, ngad
- military escalation, military buildup

### SHORT (score >= 2, SHORT dominuje) — tylko Big5 + Mid-cap
- ceasefire, peace deal, peace agreement
- diplomatic solution, negotiations
- troop withdrawal, end of conflict
- defense budget cut, doge cuts, reduced defense
- contract cancelled, program terminated, scrapped
- failed test, cost overrun, fraud
- arms embargo

---

## Parametry zleceń

### US Big-5
| Typ        | size_usd | stop_loss | take_profit |
|------------|----------|-----------|-------------|
| LONG (BUY) | **$8,000** | **−5%**   | **+12%**    |
| SHORT      | **$5,000** | **+5%**   | **−12%**    |

### US Mid-cap
| Typ        | size_usd | stop_loss | take_profit |
|------------|----------|-----------|-------------|
| LONG (BUY) | **$5,000** | **−5%**   | **+12%**    |
| SHORT      | **$4,000** | **+5%**   | **−12%**    |

### Defense ETFs (tylko LONG)
| Typ  | size_usd | stop_loss | take_profit |
|------|----------|-----------|-------------|
| LONG | **$6,000** | **−5%**   | **+12%**    |

### European ADRs (tylko LONG)
| Typ  | size_usd | stop_loss | take_profit |
|------|----------|-----------|-------------|
| LONG | **$4,000** | **−5%**   | **+12%**    |

### Geo basket (energy + GLD)
| Ticker | Direction | size_usd | SL | TP |
|--------|-----------|----------|-----|-----|
| XLE    | LONG/SHORT | **$6,000** | ±5% | ±12% |
| XOM    | LONG/SHORT | **$6,000** | ±5% | ±12% |
| GLD    | LONG only  | **$6,000** | -5% | +12% |
| CVX    | LONG/SHORT | **$6,000** | ±5% | ±12% |

- `order_type`: LIMIT
- `time_in_force`: DAY
- R:R = 2.4

---

## Zasady risk management

- Max **6 pozycji defense + geo combined** jednocześnie (poprzednio 4 + 3 = 7 — teraz combined 6)
- Nie shortujemy ETF ani European ADR
- Daily P&L stop: -12% → no new entries
- VIX HALT > 60
- Scoring musi być >= 2 dla LONG, >= 2 dla SHORT
- News musi pochodzić z ostatniej **60 minut**
- Nie otwieramy kilku tickerów z tego samego kontrahentu w jednej sesji

---

## Historia i wyniki

| Data | Ticker | Kierunek | Score | Wynik | Źródło | Notatka |
|------|--------|----------|-------|-------|--------|---------|
| —    | —      | —        | —     | —     | —      | v2.0 aktywne 2026-05-06 EOD |
