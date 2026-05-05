# Strategia: Reddit Sentiment Trading

## Opis
Wykrywanie spike wzmianek (3x 7d avg) + post DD od wiarygodnego usera.
Subreddity: r/wallstreetbets, r/investing, r/stocks.

**Cel ekspozycji:** max $2,000 w pozycjach reddit jednocześnie

---

## Warunki wejścia

### Sygnał SPIKE+DD (BUY momentum)
Warunki ALL:
- Spike >= 3x dzienna średnia z 7 dni
- Post DD od autora: karma >= 5000 (WSB) / 1000 (inne), wiek >= 180 dni
- Ticker na whitelist
- VIX < **40** (poprzednio 30)
- Rynki otwarte

### Kierunek
- Zawsze BUY (momentum, nie kontrariańskie)

---

## Parametry zlecenia

- `size_usd`: **1,000** (poprzednio 200)
- `stop_loss`: **−4%** (poprzednio −3%)
- `take_profit`: **+7%** (poprzednio +5%)
- `order_type`: LIMIT
- `time_in_force`: DAY
- R:R = 1.75

---

## Zasady risk management

- Maksymalnie **2 pozycje Reddit** jednocześnie (poprzednio 1)
- Nie otwieramy gdy dzienna strata > −3%
- VIX > 40 → stop

---

## Tickery (whitelist)
AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA, JPM, V, MA, JNJ, SPY, QQQ, XLE, XLK, GLD, RTX, LMT, NOC, XOM, CVX

---

## Historia i wyniki

| Data | Ticker | Subreddit | Spike | Wynik | Notatka |
|------|--------|-----------|-------|-------|---------|
| —    | —      | —         | —     | —     | Czeka na Reddit API |
