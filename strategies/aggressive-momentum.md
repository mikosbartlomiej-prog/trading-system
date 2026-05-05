# Strategia: Aggressive Momentum (Long + Short)

## Opis
Agresywna strategia momentum — zarabiamy zarówno na wzrostach (LONG)
jak i na spadkach (SHORT). Duże pozycje, ATR-based SL/TP, cel: maksymalizacja
zysku na paper account $100k.

**Cel ekspozycji:** max $23,000 w momentum jednocześnie (długi + krótkie)

---

## SYGNAŁ LONG — Momentum Breakout

### Warunki wejścia (ALL wymagane)
- Cena > 20-dniowe maksimum (breakout z konsolidacji)
- Wolumen dzisiejszy > 1.5x średnia wolumenu 20 dni
- RSI(14) w przedziale 50–70
- Rynki otwarte, VIX < 45

### Parametry zlecenia LONG
- `action`: BUY
- `size_usd`: **3,000**
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
- RSI(14) > 72 ← WYMAGANE
- Cena w top 2% od 20-dniowego max (resistance)
- Wolumen < 0.8x średnia 20d (zanikający impet)
- Świeca: close < poprzednie open (bearish)

### Parametry zlecenia SHORT
- `action`: SELL_SHORT
- `size_usd`: **2,000**
- `stop_loss`: cena + 1.5 × ATR(14)
- `take_profit`: cena − 2.5 × ATR(14)
- `order_type`: LIMIT
- `time_in_force`: DAY
- R:R = 1.67

### Tickery SHORT
AAPL, MSFT, GOOGL, NVDA, META, TSLA, AMZN

---

## Zasady risk management

- Maksymalnie **5 pozycji long** jednocześnie
- Maksymalnie **4 pozycje short** jednocześnie
- Nie otwieramy nowych pozycji gdy dzienna strata > **−5%**
- VIX > 45 → stop (poprzednio 35)
- ATR musi być > 0.5% ceny
- Nie shortujemy spółek z aktywnym sygnałem geo (RTX, LMT, XLE)

---

## Walidacja przez risk-officer

1. Ticker na whitelist?
2. LONG: size_usd <= 3,000? SHORT: size_usd <= 2,000?
3. SL ustawiony (ATR-based)?
4. Nie przekroczony limit (long≤5, short≤4)?
5. VIX < 45?
6. Dzienna strata < −5%?

---

## Historia i wyniki

| Data | Ticker | Kierunek | Entry | Exit | P&L% | Sygnał | Notatka |
|------|--------|----------|-------|------|------|--------|---------|
| —    | —      | —        | —     | —    | —    | —      | Parametry zaktualizowane 05.05.2026 (agresywne) |
