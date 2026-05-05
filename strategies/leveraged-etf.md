# Strategia: Leveraged ETF Trading (3x)

## Opis
Handel lewarowanymi ETF-ami (3x amplituda). Cel: szybkie duże ruchy.
Mniejszy SL tolerance ze względu na decay, ale większe rozmiary pozycji.

**Cel ekspozycji:** max $4,500 w lewarowanych ETF jednocześnie

---

## Instrumenty

| Ticker | Opis              | Kierunek | Kiedy kupować                         |
|--------|-------------------|----------|---------------------------------------|
| TQQQ   | 3x QQQ (Nasdaq)   | LONG     | QQQ w uptrend, RSI QQQ 50-65          |
| SQQQ   | -3x QQQ (short)   | LONG     | QQQ w downtrend, RSI QQQ < 35         |
| SPXL   | 3x SPY (S&P 500)  | LONG     | SPY breakout z 20d high               |
| SPXS   | -3x SPY (short)   | LONG     | SPY poniżej 20d low, RSI < 38         |
| UPRO   | 3x SPY alternatyw | LONG     | Silny SPY uptrend                     |

---

## Warunki wejścia

### Bullish (TQQQ, SPXL, UPRO)
- Indeks bazowy > 20-dniowe max (breakout)
- RSI indeksu bazowego: 50–68
- VIX < **35** (poprzednio 25 — teraz agresywniej)

### Bearish (SQQQ, SPXS)
- Indeks bazowy poniżej 20-dniowego min
- RSI indeksu bazowego < 38
- VIX < 40

---

## Parametry zlecenia

- `size_usd`: **1,500** (poprzednio 300)
- `stop_loss`: −4% od ceny wejścia
- `take_profit`: **+12%** od ceny wejścia (poprzednio +8%)
- `order_type`: LIMIT
- `time_in_force`: DAY
- R:R = 3.0
- Maksymalny czas trzymania: 2 dni

---

## Zasady risk management

- Maksymalnie **3 pozycje** lewarowane jednocześnie
- Nigdy TQQQ + SQQQ jednocześnie
- Nigdy SPXL + SPXS jednocześnie
- ETF trzymany > 48h bez ruchu → zamknij (decay)
- VIX > 35 dla bullish, > 40 dla bearish → stop

---

## Historia i wyniki

| Data | Ticker | Kierunek | Entry | Exit | P&L% | Sygnał | Notatka |
|------|--------|----------|-------|------|------|--------|---------|
| —    | —      | —        | —     | —    | —    | —      | Parametry zaktualizowane 05.05.2026 |
