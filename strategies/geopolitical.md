# Strategia: Geopolitical Event Trading

## Opis
Strategia oparta na eskalacji/deeskalacji konfliktów geopolitycznych,
szczególnie konfliktu USA-Iran-Izrael na Bliskim Wschodzie oraz
decyzjach administracji Trumpa (sankcje, taryfy, rozkazy wykonawcze).

## Warunki wejścia

### Scenariusz ESKALACJA (BUY obronne/energia/złoto)
Warunki ALL:
- Alert priorytet HIGH (score >= 3)
- News zawiera: atak, strike, Hormuz, sankcje, embargo, Iran nuclear
- VIX < 35 (powyżej = zbyt duża zmienność, nie handlujemy)
- Rynki otwarte

Aktywa i kierunek:
| Ticker | Klasa       | Kierunek | Uzasadnienie                          |
|--------|-------------|----------|---------------------------------------|
| XLE    | Energia ETF | BUY      | Zagrożenie dostaw ropy przez Ormuz    |
| XOM    | Energia     | BUY      | Beneficjent wzrostu cen ropy          |
| GLD    | Złoto       | BUY      | Safe haven przy niepewności           |
| RTX    | Obronne     | BUY      | Raytheon — systemy rakietowe          |
| LMT    | Obronne     | BUY      | Lockheed — lotnictwo wojskowe         |

### Scenariusz DEESKALACJA (kontrariański)
Warunki ALL:
- Alert o zawieszeniu broni, porozumieniu, wycofaniu wojsk
- VIX < 25
- Rynki otwarte

Aktywa i kierunek:
| Ticker | Klasa       | Kierunek | Uzasadnienie                          |
|--------|-------------|----------|---------------------------------------|
| QQQ    | Tech ETF    | BUY      | Risk-on po deeskalacji                |
| SPY    | Broad mkt   | BUY      | Odbicie rynku po napięciu             |
| XLE    | Energia ETF | SELL     | Spadek cen ropy przy deeskalacji      |

## Parametry zlecenia
- size_usd: 300 (mniejszy niż momentum, bo wyższe ryzyko geopolityczne)
- stop_loss: -2.5% (ciaśniejszy SL — geopolityka może szybko się odwrócić)
- take_profit: +4% (R:R = 1.6)
- order_type: LIMIT (nigdy MARKET)
- time_in_force: DAY

## Zasady risk management
- Maksymalnie 2 geopolityczne pozycje jednocześnie
- Nie otwieramy nowych pozycji gdy dzienna strata > -2%
- Jeśli VIX > 35 → tylko raport, żadnych zleceń
- Spółki obronne (RTX, LMT) → tylko przy bezpośrednim konflikcie zbrojnym
- Złoto (GLD) → tylko gdy news dotyczy bezpośrednio safe haven / ucieczki z rynku

## Walidacja przez risk-officer
Risk-officer sprawdza:
1. Ticker na whitelist (XLE, XOM, GLD, RTX, LMT, QQQ, SPY)?
2. size_usd <= 300?
3. SL max -2.5%?
4. Nie więcej niż 2 otwarte pozycje geo?
5. VIX < 35?
6. Strategia udokumentowana w strategies/geopolitical.md? ✓

## Źródła sygnałów
- GitHub Actions geo-monitor co 15 min
- Finnhub news API
- NewsAPI.org (Iran, Israel, Trump, Middle East, sanctions)
- BBC RSS Middle East
- Reuters RSS World/Business

## Historia i wyniki
| Data       | Ticker | Kierunek | Wynik | Notatka                    |
|------------|--------|----------|-------|----------------------------|
| 2026-05-04 | XLE    | BUY      | SKIP  | Pierwsze uruchomienie — brak strategii (już naprawione) |
