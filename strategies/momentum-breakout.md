# Momentum Breakout Strategy — v2.0

**Wersja:** 2.0 (2026-05-06 risk-on overhaul)
**Źródło prawdy:** `docs/STRATEGY.md` §4.1

## Kiedy wchodzić

- Akcja wybija 20-dniowe maksimum z wolumenem > 1.5× średnia 20d
- Cena powyżej 50-dniowej średniej kroczącej
- RSI w przedziale 50–70 (pęd, nie wykupienie)

## Entry

LIMIT order 0.2% powyżej ceny wybicia.

## Stop Loss

Bardziej luźny niż v1: entry − **2.0×ATR(14)** lub poniżej poziomu wybicia
— cokolwiek dalej (daje pozycji oddech).

## Take Profit

entry + **4.0×ATR(14)**. R:R = 2.0.
Przykład: entry $150, ATR $3 → SL $144, TP $162.

## Wielkość pozycji

**$10,000** USD per signal (was: 1% equity / ~$1,000).

## Dozwolone tickery

AAPL, MSFT, NVDA, GOOGL, META, AMZN, TSLA, SPY, QQQ
+ high-beta: COIN, MSTR, ARM, SMCI

## Risk gates

- Daily P&L stop: -12%
- VIX HALT > 60
- Max 6 long positions concurrent
