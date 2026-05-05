# Strategia: Options Trading (Calls & Puts)

## Opis
Handel opcjami jako lewarowaną ekspozycją — kupujemy calls (zakład na wzrost)
i puts (zakład na spadek). Maksymalna strata = zapłacona premia.
Nie wystawiamy nagich opcji (unlimited risk).

---

## Instrument

Alpaca obsługuje opcje na akcje amerykańskie.
Zawsze kupujemy opcje (long calls / long puts) — nigdy nie wystawiamy.

---

## SYGNAŁ CALL (zakład na wzrost)

### Kiedy kupować call
- Aktywny sygnał momentum LONG na danym tickerze
- LUB: geo-alert ESKALACJA dla sektora obronnego/energetycznego
- IV (implied volatility) < 35% — tania premia (nie kupujemy przed earnings!)
- RSI 45–65 (momentum w toku, jest dokąd rosnąć)
- 10+ dni do wygaśnięcia opcji (nie handlujemy 0–3 DTE)

### Parametry call
- `strike`: ATM lub 1 strike OTM (nie dalej niż 3% OTM)
- `expiry`: 14–21 DTE (balans między kosztem a czasem)
- `size_usd`: 150 (max premia jaką płacimy za 1 kontrakt)
- `max_contracts`: 1–2 (nie więcej)
- TP: +80% od ceny premii (2x premia)
- SL: −50% od ceny premii (nie czekamy na zero)

### Tickery do opcji (CALL)
AAPL, MSFT, NVDA, GOOGL, META, SPY, QQQ

---

## SYGNAŁ PUT (zakład na spadek)

### Kiedy kupować put
- Aktywny sygnał SHORT (RSI > 72, overbought) na danym tickerze
- LUB: geo-alert DEESKALACJA (QQQ/SPY się cofnie przy euforii)
- LUB: Reddit extreme hype na tickerze (FOMO = bliska korekta)
- IV < 45% (puts bywają droższe gdy rynek spada)
- RSI > 68 lub < 32 (skrajne warunki)

### Parametry put
- `strike`: ATM lub 1 strike OTM (nie dalej niż 3% OTM)
- `expiry`: 14–21 DTE
- `size_usd`: 150
- `max_contracts`: 1–2
- TP: +80% od ceny premii
- SL: −50% od ceny premii

### Tickery do opcji (PUT)
AAPL, MSFT, NVDA, TSLA, META, SPY, QQQ

---

## Czego UNIKAĆ

- Nigdy nie kupuj opcji dzień przed earnings (IV crush = strata gwarantowana)
- Nigdy nie kupuj opcji gdy IV > 60% (zbyt drogo)
- Nigdy 0–3 DTE (gambling, nie trading)
- Nigdy OTM > 5% od ceny spot
- Nigdy bez aktywnego sygnału z innego systemu (nie spekulujemy "na czuja")

---

## Zasady risk management

- Maksymalnie 2 otwarte pozycje opcyjne jednocześnie
- Łączny koszt premii nie może przekroczyć $300 w danym dniu
- SL automatyczny: jeśli opcja traci 50% wartości → zamknij
- TP automatyczny: jeśli opcja zyska 80% wartości → zamknij połowę
- Nie trzymamy opcji do wygaśnięcia (roll lub zamknięcie 5 dni przed)

---

## Walidacja przez risk-officer

1. Ticker na whitelist opcyjnej?
2. size_usd <= 150 na kontrakt?
3. Expiry 14–21 DTE?
4. Strike ATM lub max 3% OTM?
5. IV < 45%?
6. Nie dzień przed/po earnings?
7. Mniej niż 2 aktywne pozycje opcyjne?

---

## Historia i wyniki

| Data | Ticker | Typ | Strike | Expiry | Premia | Wynik | Sygnał | Notatka |
|------|--------|-----|--------|--------|--------|-------|--------|---------|
| —    | —      | —   | —      | —      | —      | —     | —      | Strategia aktywowana 05.05.2026 |
