# Strategia: Defense Market Trading

## Opis
Strategia oparta na analizie newsów z rynku zbrojeniowego:
kontrakty DoD, budżet militarny, eskalacja/deeskalacja konfliktów,
nowe programy zbrojeniowe, NATO.

**Częstotliwość skanowania:** co 30 minut, 24/7
**Cel ekspozycji:** max $6,000 w pozycjach defense jednocześnie

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

### US Big 5 (LONG + SHORT)
| Ticker | Spółka                   |
|--------|--------------------------|
| LMT    | Lockheed Martin          |
| RTX    | Raytheon Technologies    |
| NOC    | Northrop Grumman         |
| GD     | General Dynamics         |
| BA     | Boeing                   |

### US Mid-cap (LONG + SHORT)
| Ticker | Spółka                   |
|--------|--------------------------|
| KTOS   | Kratos Defense           |
| PLTR   | Palantir Technologies    |
| AXON   | Axon Enterprise          |
| LDOS   | Leidos Holdings          |
| SAIC   | Science Applications Int |
| CACI   | CACI International       |

### ETFs (tylko LONG)
| Ticker | Opis                     |
|--------|--------------------------|
| ITA    | iShares U.S. Aerospace   |
| XAR    | SPDR Aerospace & Defense |
| DFEN   | Direxion 3x Defense Bull |

### European ADRs (tylko LONG)
| Ticker | Spółka                   |
|--------|--------------------------|
| BAESY  | BAE Systems              |
| EADSY  | Airbus                   |

---

## Warunki wejścia

### LONG (score >= 2 słów kluczowych, LONG dominuje nad SHORT)
Słowa kluczowe LONG:
- contract awarded, contract award, awarded contract
- billion/million contract, awarded $
- indefinite delivery, idiq, government contract
- defense budget increase, increased military spending
- supplemental funding, ndaa, defense appropriations
- nato expansion, nato spending, 2% gdp, rearmament
- new weapons program, next-generation, hypersonic
- drone program, missile defense, space force
- f-35, f-47, b-21, ngad
- military escalation, heightened tensions, military buildup
- arms shipment, weapons delivery

### SHORT (score >= 2, SHORT dominuje nad LONG) — tylko Big5 + Mid-cap
Słowa kluczowe SHORT:
- ceasefire, peace deal, peace agreement, armistice
- negotiations, diplomatic solution, peace talks
- withdraw troops, troop withdrawal, end of conflict, war ends
- defense budget cut, military spending cut, reduced defense
- doge, budget reduction
- contract cancelled, program cancelled, program terminated
- failed test, test failure, scrapped
- cost overrun, investigation, fraud
- arms embargo, weapons ban

---

## Parametry zleceń

### US Big 5
| Typ        | size_usd | stop_loss | take_profit |
|------------|----------|-----------|-------------|
| LONG (BUY) | $2,500   | −3%       | +6%         |
| SHORT      | $1,500   | +3%       | −6%         |

### US Mid-cap
| Typ        | size_usd | stop_loss | take_profit |
|------------|----------|-----------|-------------|
| LONG (BUY) | $1,500   | −3%       | +6%         |
| SHORT      | $1,000   | +3%       | −6%         |

### ETFs (tylko LONG)
| Typ  | size_usd | stop_loss | take_profit |
|------|----------|-----------|-------------|
| LONG | $2,000   | −3%       | +6%         |

### European ADRs (tylko LONG)
| Typ  | size_usd | stop_loss | take_profit |
|------|----------|-----------|-------------|
| LONG | $1,000   | −3%       | +6%         |

- `order_type`: LIMIT
- `time_in_force`: DAY
- R:R = 2.0

---

## Zasady risk management

- Max **4 pozycje defense** jednocześnie (1 Big5 + 1 Mid-cap + 1 ETF + 1 European)
- Nie shortujemy ETF ani European ADR
- Nie otwieramy gdy dzienna strata > −4%
- Nie otwieramy kilku tickerów z tego samego kontrahentu za jednym razem
- Scoring musi być >= 2 dla LONG, >= 2 dla SHORT
- News musi pochodzić z ostatniej 1 godziny

---

## Historia i wyniki

| Data | Ticker | Kierunek | Score | Wynik | Źródło | Notatka |
|------|--------|----------|-------|-------|--------|---------|
| —    | —      | —        | —     | —     | —      | Czeka na pierwsze uruchomienie |
