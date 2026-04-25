---
name: alert-parsing
description: Parsuje alerty przychodzące z TradingView i normalizuje je do formatu propozycji tradu.
---

# Alert Parsing

Alerty z TradingView przychodzą jako tekst w trigger text routine'a.

## Oczekiwany format wejścia (JSON jako string)

{
  "symbol": "AAPL",
  "action": "BUY",
  "strategy": "momentum_breakout",
  "price": 150.25,
  "stop_loss": 145.00,
  "take_profit": 160.00,
  "size_usd": 1000
}

## Procedura

1. Sparsuj JSON. Jeśli błąd parsowania → zwróć { "valid": false, "error": "nieprawidłowy JSON" }
2. Sprawdź że wszystkie pola są obecne
3. Sprawdź że symbol jest wielką literą, bez spacji
4. Sprawdź że price, stop_loss, take_profit > 0
5. Sprawdź że size_usd między 100 a 10000
6. Sprawdź że plik strategies/NAZWA.md istnieje dla podanej strategii

## Wyjście jeśli OK

{
  "valid": true,
  "proposal": {
    "symbol": "AAPL",
    "action": "BUY",
    "size_usd": 1000,
    "entry_price": 150.25,
    "stop_loss": 145.00,
    "take_profit": 160.00,
    "strategy": "momentum_breakout"
  }
}

## Wyjście jeśli błąd

{
  "valid": false,
  "errors": ["lista błędów"]
}
