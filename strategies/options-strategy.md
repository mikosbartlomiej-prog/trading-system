# Strategia: Options Trading (Calls & Puts) — v2.0

**Wersja:** 2.0 (2026-05-06 risk-on overhaul) — **5× sizing, 3× max positions, AUTO-EXECUTE**
**Źródło prawdy:** `docs/STRATEGY.md` §4.6

---

## Opis
Kupno calls (wzrost) i puts (spadek). Max strata = zapłacona premia.
Nie wystawiamy nagich opcji.

**AUTO-EXECUTE na paper:** monitor sam stawia LIMIT BUY przez Alpaca REST
po przekroczeniu progu RSI (iron rule "approval each time" zliberalizowana
2026-05-06; per-run + global caps + email audit trail wymuszają safety).

**Cel ekspozycji:** max **$25,000 premium paid** w opcjach jednocześnie (was: $1,500 — wzrost 16×)

---

## SYGNAŁ CALL

### Kiedy kupować call
- Aktywny sygnał momentum LONG na danym tickerze (RSI 45-65)
- LUB: geo-alert ESKALACJA dla sektora obronnego/energetycznego
- IV < **55%** (poprzednio 35% — relaksacja)
- 7-30 dni do wygaśnięcia (poprzednio 14-21)

### Parametry call
- `strike`: ATM lub do **7% OTM** (poprzednio 3%)
- `expiry`: **7-30 DTE** (rozszerzone okno)
- `size_usd`: **$2,500** (poprzednio $500 — wzrost 5×)
- `max_contracts`: do **5** (default 1 w obecnej impl.)
- TP: **+120%** od premii (poprzednio +80%)
- SL: **−65%** od premii (poprzednio -50%)

---

## SYGNAŁ PUT

### Kiedy kupować put
- Aktywny sygnał SHORT (RSI > 72)
- LUB: Reddit extreme hype (FOMO = korekta blisko)
- IV < **65%** (poprzednio 45%)
- 7-30 DTE

### Parametry put
- `strike`: ATM lub 7% OTM (puts: lower strike)
- `expiry`: **7-30 DTE**
- `size_usd`: **$2,500**
- `max_contracts`: do **5**
- TP: **+120%** od premii
- SL: **−65%** od premii

---

## Czego UNIKAĆ

- Nigdy dzień przed/po earnings (IV crush ryzyko)
- Nigdy IV > 80% (premia za droga)
- Nigdy 0–6 DTE (theta decay zabija)
- Nigdy OTM > 7% od spot (poprzednio 5%)

---

## Zasady risk management

- Maksymalnie **10 otwartych pozycji** opcyjnych (poprzednio 3 — wzrost 3×)
- MAX_PROPOSALS_PER_RUN = **3** (poprzednio 1; rate-limit Anthropic Routines nie problem przy AUTO_EXECUTE)
- Łączny koszt premii max **$25,000** w portfelu
- Nie trzymamy opcji do wygaśnięcia (managed by `options-exit-monitor` polling)
- Daily P&L stop -12% → no new entries
- VIX HALT > 60

---

## Tickery (whitelist underlying)

AAPL, MSFT, GOOGL, NVDA, META, AMZN, TSLA, SPY, QQQ, JPM, RTX, LMT
+ (rozważyć) COIN, MSTR — bardzo high-IV, ostrożnie

---

## AUTO-EXECUTE flow (paper)

1. `options-monitor` (cron `*/10 13-20 * * 1-5`) skanuje whitelist, znajduje setup
2. Monitor pobiera chain z `/v2/options/contracts` (free, no subscription)
3. Wybiera kontrakt: closest to ATM, premium ≤ size_usd / 100
4. POSTuje simple LIMIT BUY (Alpaca paper rejects bracket na opcjach)
5. Email `[EXECUTED] {OCC} BUY_TO_OPEN_{CALL|PUT} @ ${premium}`
6. `options-exit-monitor` (cron `*/5 13-20 * * 1-5`) polluje pozycje
7. Gdy premium >= TP_target lub <= SL_target → SELL LIMIT to close
8. Email `[EXIT] {OCC} - SELL_TO_CLOSE_{TP|SL}`

---

## Historia i wyniki

| Data | Ticker | Typ | Strike | Expiry | Premia | Wynik | Sygnał | Notatka |
|------|--------|-----|--------|--------|--------|-------|--------|---------|
| 2026-05-06 | AMZN | PUT | 270 | 2026-05-20 | $3.65 | OPEN | RSI > 72 | Pierwszy paper-options trade — v1 sizing $500 budget; v2.0 update |
| —    | —    | —   | —      | —      | —      | —     | —      | v2.0 aktywne 2026-05-06 EOD |
