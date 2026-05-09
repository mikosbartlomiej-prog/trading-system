# Strategia: Reddit Sentiment Trading — v2.1

**Wersja:** 2.1 (2026-05-09 — no-API path via public JSON endpoints)
**Źródło prawdy:** `docs/STRATEGY.md` §4.7
**Status:** LIVE — `reddit-monitor/monitor.py` deployed

---

## Opis

Trzy-osiowe skanowanie Reddita **bez wymogu API approval** — używamy
publicznych endpointów `.json` z odpowiednim `User-Agent` i niskim
volumem (~10 req/h).

**Lane A — Curated subs (.claude/rules/reddit-subs.md):**
6 subów (wallstreetbets, options, stocks, investing, securityanalysis,
valueinvesting). SPIKE detection: ≥ 3× rolling 7-day mention avg
+ sentiment skew |≥ 0.3|.

**Lane B — Tracked users (.claude/rules/reddit-users.md):**
Curated lista DD writers z udokumentowanym track record. Per-user
fetch `/user/<name>/submitted.json`. Brak spike requirement —
1 high-quality post starczy. Wyższa credibility (`tracked_dd` 65 vs
random WSB `tracked_anon_trader` 55).

**Lane C** (cross-sub viral) — out of MVP scope.

**Cel ekspozycji:** max **$10,000** w Reddit positions (max 4 pozycje × $5k podstawowo, weight per-source mnoży)

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
