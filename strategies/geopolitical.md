# Strategia: Geopolitical Event Trading

## Opis
Strategia oparta na eskalacji/deeskalacji konfliktów geopolitycznych —
USA-Iran-Izrael, Bliski Wschód, decyzje administracji Trumpa.

**Cel ekspozycji:** max $4,500 w pozycjach geo jednocześnie

---

## Warunki wejścia

### Scenariusz ESKALACJA (BUY obronne/energia/złoto)
Warunki ALL:
- Alert priorytet HIGH (score >= 3)
- VIX < 45
- Rynki otwarte

| Ticker | Klasa       | Kierunek | Uzasadnienie                          |
|--------|-------------|----------|---------------------------------------|
| XLE    | Energia ETF | BUY      | Zagrożenie dostaw ropy przez Hormuz   |
| XOM    | Energia     | BUY      | Beneficjent wzrostu cen ropy          |
| GLD    | Złoto       | BUY      | Safe haven przy niepewności           |
| RTX    | Obronne     | BUY      | Raytheon — systemy rakietowe          |
| LMT    | Obronne     | BUY      | Lockheed — lotnictwo wojskowe         |

### Scenariusz DEESKALACJA
- Alert o zawieszeniu broni / porozumieniu
- VIX < 30

| Ticker | Kierunek | Uzasadnienie              |
|--------|----------|---------------------------|
| QQQ    | BUY      | Risk-on po deeskalacji    |
| SPY    | BUY      | Odbicie rynku             |
| XLE    | SELL     | Spadek cen ropy           |

---

## Parametry zlecenia

- `size_usd`: **1,500** (poprzednio 300)
- `stop_loss`: **−3%** (poprzednio −2.5%)
- `take_profit`: **+6%** (poprzednio +4%)
- `order_type`: LIMIT
- `time_in_force`: DAY
- R:R = 2.0

---

## Zasady risk management

- Maksymalnie **3 pozycje geo** jednocześnie (poprzednio 2)
- Nie otwieramy nowych gdy dzienna strata > **−3%**
- VIX > 45 → stop
- RTX, LMT → tylko przy bezpośrednim konflikcie zbrojnym
- GLD → tylko gdy news dotyczy safe haven / ucieczki z rynku

---

## Historia i wyniki

| Data       | Ticker | Kierunek | Wynik | Notatka |
|------------|--------|----------|-------|---------|
| 2026-05-04 | XLE    | BUY      | SKIP  | Pierwsze uruchomienie — brak strategii |
| 2026-05-05 | XOM    | BUY      | +0.7% | Trzymany, exit monitor → CLOSE_FLAT po 22h |
