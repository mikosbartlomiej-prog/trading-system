# Strategia: Leveraged ETF Trading (3x)

## Opis
Handel lewarowanymi ETF-ami (3x amplituda) jako sposób na szybkie,
duże zyski przy relatywnie prostej logice. Mniejsze pozycje ze względu
na 3x zmienność. Podążamy za trendem, nigdy przeciwko niemu.

---

## Instrumenty

| Ticker | Opis              | Kierunek | Kiedy kupować                         |
|--------|-------------------|----------|---------------------------------------|
| TQQQ   | 3x QQQ (Nasdaq)   | LONG     | QQQ w uptrend, RSI QQQ 50-65          |
| SQQQ   | -3x QQQ (short)   | LONG     | QQQ w downtrend, RSI QQQ < 35         |
| SPXL   | 3x SPY (S&P 500)  | LONG     | SPY breakout z 20d high               |
| SPXS   | -3x SPY (short)   | LONG     | SPY poniżej 20d low, RSI < 38         |
| UPRO   | 3x SPY alternatyw | LONG     | Silny SPY uptrend (backup dla SPXL)   |

**Uwaga:** Zawsze kupujemy (BUY) — nigdy shortujemy lewarowanych ETF
(podwójny lewar = ekstremalnie ryzykowne). SQQQ/SPXS to gotowe shorty.

---

## Warunki wejścia

### Bullish (TQQQ, SPXL, UPRO)
- Indeks bazowy (QQQ/SPY) > 20-dniowe max (breakout)
- RSI indeksu bazowego: 50–68
- Wolumen TQQQ/SPXL > 1.3x średnia 10d (wystarczy mniejszy próg)
- VIX < 25 (lewarowane ETF wymagają spokojnego rynku)

### Bearish (SQQQ, SPXS)
- Indeks bazowy poniżej 20-dniowego min (breakdown)
- RSI indeksu bazowego < 38
- VIX < 40 (poniżej paniki — przy VIX > 40 rynek może odwrócić się błyskawicznie)

---

## Parametry zlecenia

- `size_usd`: 300 (mniejszy niż zwykłe akcje — 3x volatility)
- `stop_loss`: −4% od ceny wejścia (lewarowane mogą się szybko odwrócić)
- `take_profit`: +8% od ceny wejścia (R:R = 2.0)
- `order_type`: LIMIT
- `time_in_force`: DAY
- Maksymalny czas trzymania: 2 dni (lewarowane tracą na decay przy bocznym rynku)

---

## Zasady risk management

- Maksymalnie 2 pozycje lewarowane ETF jednocześnie
- Nigdy TQQQ + SQQQ jednocześnie (hedge = brak sensu)
- Nigdy SPXL + SPXS jednocześnie
- Wymagany VIX < 25 dla bullish, < 40 dla bearish
- Jeśli ETF trzymany > 48h bez ruchu → zamknij (decay kosztuje)
- Nie łączymy z pozycją short na tym samym indeksie (QQQ short + SQQQ = duplikacja)

---

## Monitoring exit (specjalny)

Exit monitor co godzinę sprawdza:
- Zysk > +5% → rozważ częściowe zamknięcie (trailing stop)
- Strata > −3% → zamknij (szybciej niż normalny SL — 3x decay)
- ETF trzymany > 2 dni → zamknij niezależnie od P&L

---

## Historia i wyniki

| Data | Ticker | Kierunek | Entry | Exit | P&L% | Sygnał | Notatka |
|------|--------|----------|-------|------|------|--------|---------|
| —    | —      | —        | —     | —    | —    | —      | Strategia aktywowana 05.05.2026 |
