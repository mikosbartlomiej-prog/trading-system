# Strategia: Reddit Sentiment Trading

## Opis
Strategia oparta na wykrywaniu anomalii sentymentu na Reddit — spike wzmianek
tickera (3x dzienna średnia z 7 dni) połączony z postem Due Diligence od
wiarygodnego użytkownika. Subreddity: r/wallstreetbets, r/investing, r/stocks.

## Warunki wejścia

### Sygnał SPIKE+DD (BUY momentum)
Warunki ALL:
- Wzmianka tickera w ostatnich 24h >= 3x dzienna średnia z ostatnich 7 dni
- Istnieje post DD (flair lub tytuł zawiera: "dd", "due diligence", "analysis",
  "deep dive", "research", "thesis") dotyczący tego tickera
- Autor DD posta spełnia kryteria wiarygodności:
  - r/wallstreetbets: karma >= 5000, wiek konta >= 180 dni
  - r/investing, r/stocks: karma >= 1000, wiek konta >= 180 dni
- Ticker na whitelist (AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA, JPM,
  V, MA, JNJ, SPY, QQQ, XLE, XLK, GLD, RTX, LMT, NOC, XOM, CVX)
- VIX < 30 (Reddit hype + wysoka zmienność = zbyt ryzykowne)
- Rynki otwarte

### Kierunek
- Sygnał ze spike + DD → zawsze BUY (momentum, nie kontrariańskie)

## Parametry zlecenia
- size_usd: 200 (mniejszy niż momentum/geo — sygnał mniej wiarygodny)
- stop_loss: -3% (szerszy SL — retail momentum może trwać)
- take_profit: +5% (R:R = 1.67)
- order_type: LIMIT
- time_in_force: DAY

## Zasady risk management
- Maksymalnie 1 pozycja Reddit jednocześnie (nie stackujemy hype'u)
- Nie otwieramy nowych pozycji gdy dzienna strata > -2%
- Jeśli VIX > 30 → tylko raport, żadnych zleceń
- Nie handlujemy tickerami, które nie są na whitelist
- WSB hype na spółkę obronną (RTX, LMT) → wymagane dodatkowe potwierdzenie
  z geo-monitora lub momentum systemu

## Walidacja przez risk-officer
Risk-officer sprawdza:
1. Ticker na whitelist?
2. size_usd <= 200?
3. SL max -3%?
4. Nie więcej niż 1 otwarta pozycja reddit?
5. VIX < 30?
6. Spike ratio >= 3.0?
7. DD post od zweryfikowanego autora?
8. Strategia udokumentowana w strategies/reddit-sentiment.md? ✓

## Źródła sygnałów
- GitHub Actions reddit-monitor co 6h (7:00, 13:00, 16:00, 20:00 UTC)
- Reddit API: r/wallstreetbets, r/investing, r/stocks
- Tylko hot posty (ostatnie 24h)
- Ticker extraction: $TICKER format + whitelist matching

## Format alertu (payload JSON)
```json
{
  "type": "reddit_sentiment_alert",
  "timestamp": "...",
  "signals": [
    {
      "ticker": "NVDA",
      "subreddit": "wallstreetbets",
      "mentions_24h": 18,
      "daily_avg_7d": 4.2,
      "spike_ratio": 4.3,
      "signal_type": "SPIKE+DD",
      "dd_posts": [
        {
          "title": "NVDA DD — why this rally has legs",
          "author": "...",
          "score": 1240,
          "url": "https://reddit.com/...",
          "reason": "karma=12500, age=420d"
        }
      ]
    }
  ]
}
```

## Historia i wyniki
| Data       | Ticker | Subreddit       | Spike | Wynik | Notatka                    |
|------------|--------|-----------------|-------|-------|----------------------------|
| —          | —      | —               | —     | —     | System w trakcie budowy — czeka na Reddit API |
