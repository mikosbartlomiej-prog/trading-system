# Strategia: Crypto Trading (BTC, ETH)

## Opis
24/7 handel kryptowalutami przez Alpaca. Wysoka zmienność = szybkie
duże zyski (i straty). Mniejsze pozycje, szerszy SL. Monitorowanie
non-stop przez GitHub Actions co 30 minut.

---

## Instrumenty

| Symbol       | Opis          | Alpaca ticker |
|--------------|---------------|---------------|
| Bitcoin      | BTC           | BTC/USD       |
| Ethereum     | ETH           | ETH/USD       |

---

## Sygnały wejścia

### LONG Crypto (Momentum)
Wszystkie 3 warunki:
- Cena > 20-świecowe max (1h timeframe) — breakout na 1h
- Wolumen ostatniej świecy > 2x średnia z poprzednich 10 świec
- RSI(14) na 1h chart: 45–68

### SHORT Crypto (Bearish)
Wszystkie 3 warunki:
- Cena < 20-świecowe min (1h timeframe) — breakdown
- RSI(14) < 35 (oversold z trendem spadkowym, nie korekta)
- Wolumen na czerwonej świecy > 1.5x średnia

### Dodatkowe filtry
- Nie handlujemy 30 minut przed/po ważnych danych makro (CPI, FOMC)
- Nie wchodzimy gdy BTC dominance gwałtownie rośnie (panika → altcoiny lecą)
- Weekendy: zmniejszamy size_usd o 50% (niższa płynność)

---

## Parametry zlecenia

| Parametr    | LONG       | SHORT      |
|-------------|------------|------------|
| size_usd    | 250        | 200        |
| stop_loss   | −4%        | +4%        |
| take_profit | +8%        | −8%        |
| order_type  | LIMIT      | LIMIT      |
| R:R         | 2.0        | 2.0        |

**Weekendy:** size_usd × 0.5 (125/100 USD)

---

## Harmonogram monitorowania

GitHub Actions: co 30 minut, 24/7 (włącznie z weekendami)
Osobny workflow: `crypto-monitor.yml`
Osobny Cloudflare Worker: `crypto-proxy`
Osobna Claude Routine: `Crypto Handler`

---

## Zasady risk management

- Maksymalnie 1 pozycja BTC jednocześnie
- Maksymalnie 1 pozycja ETH jednocześnie
- Łącznie max 2 crypto pozycje
- Nie trzymamy crypto > 24h (wysoka zmienność, plan na krótkie ruchy)
- Jeśli pozycja trzymana > 12h bez +3% → zamknij (brak momentum)
- VIX proxy dla crypto: jeśli BTC/ETH spread > 5% w ciągu 1h → stop trading (ekstremalna zmienność)
- Dzienna strata crypto > −$50 → stop na resztę dnia

---

## Exit Monitor (specjalny dla crypto)

Co 30 minut sprawdzamy każdą crypto pozycję:
- Zysk > +5% → ustaw trailing stop 2%
- Strata > −3% → zamknij (nie czekaj na −4% SL)
- Pozycja > 12h z P&L < 2% → zamknij

---

## Korelacja z innymi systemami

- Pozytywny Reddit sentiment na BTC/ETH → zwiększ size o 20%
- Geo-alert HIGH (risk-off) → zamknij otwarte crypto long pozycje
- SPY spada > 2% w ciągu dnia → nie otwieraj nowych crypto longs

---

## Historia i wyniki

| Data | Symbol | Kierunek | Entry | Exit | P&L% | Sygnał | Notatka |
|------|--------|----------|-------|------|------|--------|---------|
| —    | —      | —        | —     | —    | —    | —      | Strategia aktywowana 05.05.2026 |
