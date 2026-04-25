---
name: place-bracket-order
description: Składa bracket order na Alpaca (entry + stop loss + take profit). Używaj tylko po APPROVE od risk-officer.
allowed-tools: mcp__alpaca__*
---

# Place Bracket Order

Składa jedno skoordynowane zlecenie: wejście + stop loss + take profit.

## Wejście

{
  "symbol": "AAPL",
  "side": "buy",
  "notional": 1500,
  "limit_price": 150.25,
  "stop_loss": 145.00,
  "take_profit": 160.00
}

## Procedura

1. Sprawdź że market jest otwarty (NYSE godziny 9:30-16:00 ET)
2. Sprawdź buying power przez Alpaca MCP
3. Złóż zlecenie:
   - type: limit
   - time_in_force: day
   - order_class: bracket
   - stop_loss.stop_price = podana wartość
   - take_profit.limit_price = podana wartość

4. Poczekaj na potwierdzenie — odczytaj order ID
5. Zwróć:
{
  "success": true/false,
  "order_id": "...",
  "status": "...",
  "error": "... (jeśli fail)"
}

## Jeśli coś pójdzie nie tak

- "insufficient buying power" → zwróć success: false, NIE rób retry
- Błąd serwera Alpaca → 1 retry po 10 sekundach, potem fail
- Każdy inny błąd → zwróć success: false z treścią błędu
