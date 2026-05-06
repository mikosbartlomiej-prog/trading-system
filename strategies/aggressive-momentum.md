# Strategia: Aggressive Momentum (Long + Short) — v2.0

**Wersja:** 2.0 (2026-05-06 risk-on overhaul) — **3.3× większe pozycje vs v1.1**
**Źródło prawdy:** `docs/STRATEGY.md` §4.1, §4.2

---

## Opis
Agresywna strategia momentum — zarabiamy zarówno na wzrostach (LONG)
jak i na spadkach (SHORT). Duże pozycje, ATR-based SL/TP z szerszą
tolerancją (2.0×ATR / 4.0×ATR), cel: maksymalizacja zysku przy pełnym
deployment kapitału.

**Cel ekspozycji:** max **$60,000 gross** w momentum jednocześnie (long + short)

---

## SYGNAŁ LONG — Momentum Breakout

### Warunki wejścia (ALL wymagane)
- Cena > 20-dniowe maksimum (breakout z konsolidacji)
- Wolumen dzisiejszy > 1.5× średnia wolumenu 20 dni
- RSI(14) w przedziale 50–70
- Rynki otwarte
- VIX < 60 (catastrophic-only halt)

### Parametry zlecenia LONG
- `action`: BUY
- `size_usd`: **$10,000** (poprzednio $3,000)
- `stop_loss`: cena − **2.0** × ATR(14)   (poprzednio 1.5×)
- `take_profit`: cena + **4.0** × ATR(14) (poprzednio 2.5×)
- `order_type`: LIMIT
- `time_in_force`: DAY
- R:R = 2.0

### Tickery LONG
AAPL, MSFT, GOOGL, NVDA, META, AMZN, TSLA, SPY, QQQ
+ high-beta: COIN, MSTR, ARM, SMCI (dodane 2026-05-06)

---

## SYGNAŁ SHORT — Overbought Reversal

### Warunki wejścia (RSI wymagane + 2 z 3 dodatkowych)
- RSI(14) > 72 ← WYMAGANE
- Cena w top 2% od 20-dniowego max (resistance)
- Wolumen < 0.8× średnia 20d (zanikający impet)
- Świeca: close < poprzednie open (bearish)

### Parametry zlecenia SHORT
- `action`: SELL_SHORT
- `size_usd`: **$8,000** (poprzednio $2,000)
- `stop_loss`: cena + **2.0** × ATR(14)   (poprzednio 1.5×)
- `take_profit`: cena − **4.0** × ATR(14) (poprzednio 2.5×)
- `order_type`: LIMIT
- `time_in_force`: DAY
- R:R = 2.0

### Tickery SHORT
AAPL, MSFT, GOOGL, NVDA, META, TSLA, AMZN

---

## Zasady risk management

- Maksymalnie **6 pozycji long** jednocześnie (poprzednio 5)
- Maksymalnie **4 pozycje short** jednocześnie (bez zmian)
- Daily P&L stop: **-12%** (poprzednio -5%) — wtedy nie otwieramy nowych
- VIX: HALT tylko > 60; CAUTION mode usunięty
- ATR musi być > 0.5% ceny (filtr płynności)
- Nie shortujemy spółek z aktywnym sygnałem geo (RTX, LMT, XLE)
- Margin używany aktywnie — pełna buying power dostępna

---

## Walidacja przez risk-officer

Risk-officer (v2.0, default APPROVE) sprawdza:
1. Ticker na whitelist?
2. LONG: size_usd <= $10,000? SHORT: size_usd <= $8,000?
3. SL ustawiony (ATR-based)?
4. Nie przekroczony limit (long ≤ 6, short ≤ 4)?
5. Nie przekroczony per-ticker cap 40% equity?
6. Nie przekroczony daily loss -12%?

---

## Historia i wyniki

| Data | Ticker | Kierunek | Entry | Exit | P&L% | Sygnał | Notatka |
|------|--------|----------|-------|------|------|--------|---------|
| —    | —      | —        | —     | —    | —    | —      | v2.0 risk-on aktywne 2026-05-06 EOD |
