# Strategia: Reddit Sentiment Trading — v2.0

**Wersja:** 2.0 (2026-05-06 risk-on overhaul) — **5× sizing**
**Źródło prawdy:** `docs/STRATEGY.md` §4.7
**Status:** PAUSED — czeka na approval Reddit API

---

## Opis
Wykrywanie spike wzmianek (3× 7-day avg) + post DD od wiarygodnego usera.
Subreddity: r/wallstreetbets, r/investing, r/stocks.

**Cel ekspozycji:** max **$10,000** w Reddit positions (5× wzrost vs v1)

---

## Warunki wejścia

### Sygnał SPIKE+DD (BUY momentum)
Warunki ALL:
- Spike >= 3× dzienna średnia z 7 dni
- Post DD od autora: karma >= 5000 (WSB) / 1000 (inne), wiek konta >= 180 dni
- Ticker na whitelist
- VIX < 60 (HALT only above)
- Rynki otwarte

### Kierunek
- Zawsze BUY (momentum, nie kontrariańskie)

---

## Parametry zlecenia

- `size_usd`: **$5,000** (poprzednio $1,000 — wzrost 5×)
- `stop_loss`: **−6%** (poprzednio −4%)
- `take_profit`: **+14%** (poprzednio +7%)
- `order_type`: LIMIT
- `time_in_force`: DAY
- R:R = 2.33

---

## Zasady risk management

- Maksymalnie **4 pozycje Reddit** jednocześnie (poprzednio 2 — wzrost 2×)
- Daily P&L stop -12%
- VIX HALT > 60

---

## Tickery (whitelist Reddit)

AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA
JPM, V, MA, JNJ
SPY, QQQ
XLE, XLK, GLD
RTX, LMT, NOC
XOM, CVX
+ high-beta: COIN, MSTR, ARM, SMCI

---

## Historia i wyniki

| Data | Ticker | Subreddit | Spike | Wynik | Notatka |
|------|--------|-----------|-------|-------|---------|
| —    | —      | —         | —     | —     | Czeka na Reddit API approval |
