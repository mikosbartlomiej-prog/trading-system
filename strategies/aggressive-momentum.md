# Strategia: Aggressive Momentum (Long + Short)

## Opis
Agresywna strategia momentum — zarabiamy zarówno na wzrostach (LONG)
jak i na spadkach (SHORT). Wyższe rozmiary pozycji, ATR-based SL/TP
zamiast stałych %. Cel: szybkie duże zyski przy aktywnym zarządzaniu ryzykiem.

---

## SYGNAŁ LONG — Momentum Breakout

### Warunki wejścia (ALL wymagane)
- Cena > 20-dniowe maksimum (breakout z konsolidacji)
- Wolumen dzisiejszy > 1.5x średnia wolumenu 20 dni (potwierdzenie siły)
- RSI(14) w przedziale 50–70 (momentum bez wykupienia)
- Rynki otwarte, VIX < 35

### Parametry zlecenia LONG
- `action`: BUY
- `size_usd`: 600
- `stop_loss`: cena − 1.5 × ATR(14)
- `take_profit`: cena + 2.5 × ATR(14)
- `order_type`: LIMIT
- `time_in_force`: DAY
- R:R = 1.67

### Tickery LONG
AAPL, MSFT, GOOGL, NVDA, SPY, META, AMZN

---

## SYGNAŁ SHORT — Overbought Reversal

### Warunki wejścia (RSI wymagane + 2 z 3 dodatkowych)
- RSI(14) > 72 (ekstremalnie wykupiony) ← WYMAGANE
- Cena w top 2% od 20-dniowego max (strefa resistance) ← 2 z poniżej:
- Wolumen < 0.8x średnia 20d (zanikający impet)
- Świeca dzisiejsza: close < poprzednie open (bearish candle)

### Parametry zlecenia SHORT
- `action`: SELL_SHORT
- `size_usd`: 400 (mniejszy niż long — short bardziej ryzykowne)
- `stop_loss`: cena + 1.5 × ATR(14) ← SL POWYŻEJ ceny (short!)
- `take_profit`: cena − 2.5 × ATR(14) ← TP PONIŻEJ ceny (short!)
- `order_type`: LIMIT
- `time_in_force`: DAY
- R:R = 1.67

### Tickery SHORT
AAPL, MSFT, GOOGL, NVDA, META, TSLA, AMZN

---

## Zasady risk management

- Maksymalnie 3 pozycje long jednocześnie
- Maksymalnie 2 pozycje short jednocześnie
- Łącznie max 4 otwarte pozycje momentum (long+short)
- Nie otwieramy nowych pozycji gdy dzienna strata > -3%
- VIX > 35 → tylko raporty, bez zleceń
- Nie shortujemy spółek z aktywnym byuym sygnałem geo (RTX, LMT, XLE)
- ATR musi być > 0.5% ceny (brak sygnałów przy zerowej zmienności)

---

## Walidacja przez risk-officer

Risk-officer sprawdza:
1. Ticker na whitelist momentum?
2. LONG: size_usd <= 600? SHORT: size_usd <= 400?
3. SL ustawiony (ATR-based)?
4. Nie przekroczony limit pozycji (long≤3, short≤2)?
5. VIX < 35?
6. Dzienna strata < -3%?
7. Strategia udokumentowana w strategies/aggressive-momentum.md? ✓

---

## Historia i wyniki

| Data | Ticker | Kierunek | Entry | Exit | P&L% | Sygnał | Notatka |
|------|--------|----------|-------|------|------|--------|---------|
| —    | —      | —        | —     | —    | —    | —      | Strategia aktywowana 05.05.2026 |
