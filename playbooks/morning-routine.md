# Morning Routine Playbook

Uruchamiany codziennie o 8:30 czasu zuryskiego, przed otwarciem NYSE.

## Co robić (w kolejności)

1. Wywołaj skill portfolio-snapshot — pobierz stan konta
2. Sprawdź VIX przez Alpaca MCP (ticker VIXY jako proxy)
3. Sprawdź aktualne ceny SPY i QQQ
4. Przejrzyj otwarte zlecenia — czy któreś wygasa dziś?
5. Wygeneruj raport morning brief w formacie z .claude/rules/report-format.md
6. Zapisz brief do pliku briefs/YYYY-MM-DD.md
7. Wyślij na Slack #trading (jeśli dostępny)

## Czego NIE robić

NIE składaj żadnych zleceń. To tylko raport.
