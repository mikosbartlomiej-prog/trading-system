# Strategia: Crypto Trading (BTC, ETH)

## Opis
24/7 handel kryptowalutami przez Alpaca. LIMIT DOLAROWY zamiast
limitu liczby pozycji — ma sens przy BTC=$78k i ETH=$2.3k.

**Cel ekspozycji:** max **$8,000** w crypto łącznie w każdej chwili

---

## Instrumenty

| Symbol   | Opis      | Alpaca ticker |
|----------|-----------|---------------|
| Bitcoin  | BTC       | BTC/USD       |
| Ethereum | ETH       | ETH/USD       |

---

## Rozmiary pozycji

| Instrument | Weekday | Weekend |
|------------|---------|---------|
| BTC/USD long | **$2,000** | **$1,000** |
| BTC/USD short | **$1,500** | **$750** |
| ETH/USD long | **$1,000** | **$500** |
| ETH/USD short | **$800** | **$400** |

**Limit całkowity:** max $8,000 w crypto jednocześnie (8% konta $100k)
- Jeśli suma otwartych pozycji crypto >= $7,000 → nie otwieraj nowych

---

## Sygnały wejścia

### LONG Crypto (Momentum)
- Cena > 20-świecowe max (1h timeframe)
- Wolumen ostatniej świecy > 2x średnia z 10 świec
- RSI(14) na 1h: 45–68

### SHORT Crypto (Bearish)
- Cena < 20-świecowe min (1h timeframe)
- RSI(14) < 35
- Wolumen > 1.5x średnia

---

## Parametry zlecenia

| Parametr    | LONG  | SHORT |
|-------------|-------|-------|
| stop_loss   | −5%   | +5%   |
| take_profit | +12%  | −12%  |
| order_type  | LIMIT | LIMIT |
| R:R         | 2.4   | 2.4   |

---

## Exit Monitor (specjalny dla crypto)

Co 30 minut:
- Zysk > +6% → ustaw trailing stop 2%
- Strata > −4% → zamknij wcześniej
- Pozycja > 12h z P&L < 2% → zamknij (brak momentum)

---

## Korelacja z innymi systemami

- Geo-alert HIGH (risk-off) → zamknij otwarte crypto long pozycje
- SPY spada > 3% w ciągu dnia → nie otwieraj nowych crypto longs

---

## Historia i wyniki

| Data | Symbol | Kierunek | Entry | Exit | P&L% | Sygnał | Notatka |
|------|--------|----------|-------|------|------|--------|---------|
| —    | —      | —        | —     | —    | —    | —      | Parametry zaktualizowane 05.05.2026 — limit dolarowy |
