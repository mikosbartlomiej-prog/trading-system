# Trading System — Konstytucja

## Środowisko
Pracuję na PAPER TRADING (env var ALPACA_PAPER=true).
NIE wykonuję żadnych operacji na prawdziwym koncie dopóki ALPACA_PAPER=false.

## Żelazne zasady — naruszenie = natychmiastowe zatrzymanie sesji

### Limity wielkości pozycji
- Maksymalny pojedynczy trade: 5% wartości konta (equity)
- Maksymalna ekspozycja na jeden ticker: 15% equity
- Minimum cash: zawsze zostaw 5% konta jako cash
- Daily loss limit: jeśli łączna strata dnia > 3% equity → STOP, żadnych nowych pozycji

### Dozwolone tickery — TYLKO z tej listy
Pełna lista: .claude/rules/tickers-whitelist.md
Próba tradowania poza listą = natychmiastowy abort.

### Rodzaje zleceń
- Zawsze LIMIT order (nigdy MARKET)
- Każde wejście w pozycję = bracket order: entry + stop loss + take profit
- Time in force: DAY (chyba że strategia mówi inaczej)

### Czego nie wolno
- Opcje — bez mojej wyraźnej zgody
- Lewarowanie / margin
- Handel gdy VIX powyżej 35
- Handel 30 minut przed i po publikacji wyników finansowych spółki

## Obowiązkowy workflow dla każdego zlecenia
1. Deleguj do sub-agenta risk-officer (.claude/agents/risk-officer.md)
2. Jeśli APPROVE → wykonaj przez skill place-bracket-order
3. Jeśli REJECT → zapisz powód, NIE handluj
4. Zawsze → zapis do journal/trades-YYYY-MM-DD.md

## Komunikacja
- Raporty po polsku
- Każde wykonane/odrzucone zlecenie → Slack #trading (jeśli skonfigurowany)
- Format raportu: .claude/rules/report-format.md
