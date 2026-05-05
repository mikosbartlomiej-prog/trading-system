# Strategia: Options Trading (Calls & Puts)

## Opis
Kupno calls (wzrost) i puts (spadek). Max strata = zapłacona premia.
Nie wystawiamy nagich opcji.

**Cel ekspozycji:** max $1,500 w opcjach jednocześnie

---

## SYGNAŁ CALL

### Kiedy kupować call
- Aktywny sygnał momentum LONG na danym tickerze
- LUB: geo-alert ESKALACJA dla sektora obronnego/energetycznego
- IV < 35% (tania premia)
- RSI 45–65
- 10+ dni do wygaśnięcia

### Parametry call
- `strike`: ATM lub 1 strike OTM (max 3% OTM)
- `expiry`: 14–21 DTE
- `size_usd`: **500** (poprzednio 150)
- `max_contracts`: 1–2
- TP: +80% od premii
- SL: −50% od premii

---

## SYGNAŁ PUT

### Kiedy kupować put
- Aktywny sygnał SHORT (RSI > 72)
- LUB: Reddit extreme hype (FOMO = korekta blisko)
- IV < 45%

### Parametry put
- `strike`: ATM lub 1 strike OTM
- `expiry`: 14–21 DTE
- `size_usd`: **500** (poprzednio 150)
- `max_contracts`: 1–2
- TP: +80% od premii
- SL: −50% od premii

---

## Czego UNIKAĆ
- Nigdy dzień przed/po earnings
- Nigdy IV > 60%
- Nigdy 0–3 DTE
- Nigdy OTM > 5% od spot

---

## Zasady risk management
- Maksymalnie **3 otwarte pozycje** opcyjne
- Łączny koszt premii max $1,000 w ciągu dnia
- Nie trzymamy opcji do wygaśnięcia

---

## Historia i wyniki

| Data | Ticker | Typ | Strike | Expiry | Premia | Wynik | Sygnał | Notatka |
|------|--------|-----|--------|--------|--------|-------|--------|---------|
| —    | —      | —   | —      | —      | —      | —     | —      | Parametry zaktualizowane 05.05.2026 |
