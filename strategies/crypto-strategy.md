# Strategia: Crypto Trading (BTC, ETH) — v2.0

**Wersja:** 2.0 (2026-05-06 risk-on overhaul) — **4× sizing, weekend halving usunięty**
**Źródło prawdy:** `docs/STRATEGY.md` §4.4

---

## Opis
24/7 handel BTC/USD i ETH/USD przez Alpaca. Pełne sizing przez 7 dni
tygodnia (poprzednio weekend halved). Limit dolarowy zamiast limitu
liczby pozycji — sensowne przy BTC ~$100k i ETH ~$3k.

**Cel ekspozycji:** max **$25,000** w crypto łącznie w każdej chwili (3× wzrost vs v1)

---

## Instrumenty

| Symbol   | Opis      | Alpaca ticker |
|----------|-----------|---------------|
| Bitcoin  | BTC       | BTC/USD       |
| Ethereum | ETH       | ETH/USD       |

---

## Rozmiary pozycji (no weekend discount)

| Instrument     | Weekday | Weekend |
|----------------|---------|---------|
| BTC/USD long   | **$8,000** | **$8,000** |
| BTC/USD short  | **$6,000** | **$6,000** |
| ETH/USD long   | **$4,000** | **$4,000** |
| ETH/USD short  | **$3,000** | **$3,000** |

**Limit całkowity:** $25,000 gross (poprzednio $8,000 — wzrost 3×)
- Jeśli suma otwartych pozycji crypto >= $20,000 → nie otwieraj nowych

---

## Sygnały wejścia (1-hour timeframe)

### LONG Crypto (Momentum)
- Cena > 20-świecowe max (1h)
- Wolumen ostatniej świecy > 2× średnia 10 świec
- RSI(14) na 1h: 45–68

### SHORT Crypto (Bearish)
- Cena < 20-świecowe min (1h)
- RSI(14) < 35
- Wolumen > 1.5× średnia

---

## Parametry zlecenia

| Parametr    | LONG    | SHORT   |
|-------------|---------|---------|
| stop_loss   | **−7%** | **+7%** (poprzednio ±5%) |
| take_profit | **+20%**| **−20%** (poprzednio ±12%) |
| order_type  | LIMIT   | LIMIT   |
| R:R         | 2.86    | 2.86    |

---

## Exit Monitor (specjalny dla crypto)

Co 30 minut, plus exit-monitor co godzinę:
- Zysk > +10% → ustaw trailing stop 4%
- Strata > -5% → consider close (ale przed SL -7%)
- Pozycja > **48h** z P&L < 5% → CLOSE_DECAY (poprzednio 12h)

---

## Korelacja z innymi systemami

- Geo-alert HIGH (risk-off) → zamknij otwarte crypto LONG
- SPY spada > 4% w ciągu dnia → nie otwieraj nowych crypto longs (krach risk-off zwykle dotyka też BTC)
- VIX > 60 → HALT (jak wszystko inne)

---

## Historia i wyniki

| Data | Symbol | Kierunek | Entry | Exit | P&L% | Sygnał | Notatka |
|------|--------|----------|-------|------|------|--------|---------|
| —    | —      | —        | —     | —    | —    | —      | v2.0 aktywne 2026-05-06 EOD |
