# Strategia: Leveraged ETF Trading (3×) — v2.0

**Wersja:** 2.0 (2026-05-06 risk-on overhaul) — **4× większy size, lista 3× szersza**
**Źródło prawdy:** `docs/STRATEGY.md` §4.3

---

## Opis
Handel lewarowanymi ETF-ami (3× amplituda). Cel: szybkie duże ruchy.
Mniejsza tolerancja decay = krótkie horyzonty (max 96h), ale **dużo
większe rozmiary pozycji** w v2.

**Cel ekspozycji:** max **$25,000 gross** w lewarowanych ETF jednocześnie (8× v1)

---

## Instrumenty

### Bullish (LONG when underlying breaks out)
| Ticker | 3× kierunek | Bazowy indeks  | Kupujemy gdy            |
|--------|-------------|----------------|-------------------------|
| TQQQ   | 3× QQQ       | Nasdaq-100     | QQQ uptrend, RSI 50-68  |
| SPXL   | 3× SPY       | S&P 500        | SPY breakout 20d high   |
| UPRO   | 3× SPY (alt) | S&P 500        | Silny SPY uptrend       |
| SOXL   | 3× SOX       | Semis          | SMH breakout, RSI 50-68 |
| FAS    | 3× XLF       | Financials     | XLF breakout            |
| TNA    | 3× IWM       | Russell 2000   | Small-cap breakout      |

### Bearish (LONG inverse 3×)
| Ticker | -3× kierunek | Kupujemy gdy            |
|--------|--------------|-------------------------|
| SQQQ   | -3× QQQ       | QQQ downtrend, RSI < 38 |
| SPXS   | -3× SPY       | SPY breakdown           |
| SPXU   | -3× SPY (alt) | SPY breakdown alt       |
| SOXS   | -3× SOX       | SMH breakdown           |
| FAZ    | -3× XLF       | XLF breakdown           |
| TZA    | -3× IWM       | Russell breakdown       |

---

## Warunki wejścia

### Bullish (TQQQ/SPXL/UPRO/SOXL/FAS/TNA)
- Indeks bazowy > 20-dniowe max (breakout)
- RSI indeksu bazowego: 50–68
- VIX < 60 (catastrophic only)

### Bearish (SQQQ/SPXS/SPXU/SOXS/FAZ/TZA)
- Indeks bazowy poniżej 20-dniowego min
- RSI indeksu bazowego < 38
- VIX < 60

---

## Parametry zlecenia

- `size_usd`: **$6,000** (poprzednio $1,500 — 4× wzrost)
- `stop_loss`: **−5%** od ceny wejścia (poprzednio -4%)
- `take_profit`: **+18%** od ceny wejścia (poprzednio +12%)
- `order_type`: LIMIT
- `time_in_force`: DAY
- R:R = 3.6
- Maksymalny czas trzymania: **96h** (poprzednio 48h)

---

## Zasady risk management

- Maksymalnie **4 pozycje** lewarowane jednocześnie (poprzednio 3)
- Nigdy TQQQ + SQQQ jednocześnie (offsetting)
- Nigdy SPXL + SPXS jednocześnie
- Nigdy SOXL + SOXS jednocześnie
- ETF trzymany > 96h bez ruchu → CLOSE_DECAY (decay zjada zysk)
- Daily P&L stop: -12% → no new entries
- VIX HALT > 60

---

## Decay awareness

3× ETFs decay przy zmienności bocznej (-1% dziennie typowo). Stąd:
- preferujemy entry przy WYSOKIM momentum (RSI, breakout) gdzie kierunek jest jasny
- 96h to BARDZO długi horyzont dla 3×; zwykle sygnał albo działa w 1-2 dni, albo umiera

---

## Historia i wyniki

| Data | Ticker | Kierunek | Entry | Exit | P&L% | Sygnał | Notatka |
|------|--------|----------|-------|------|------|--------|---------|
| —    | —      | —        | —     | —    | —    | —      | v2.0 aktywne 2026-05-06 EOD |
