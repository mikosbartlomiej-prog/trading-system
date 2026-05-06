---
name: portfolio-snapshot
description: Pobiera pełny stan portfela z Alpaca. Używaj na początku każdej sesji decyzyjnej.
allowed-tools: mcp__alpaca__*
---

# Portfolio Snapshot

Pobiera i zwraca kompletny obraz konta.

## Procedura

Wywołaj równolegle:
1. get_account — equity, cash, buying_power
2. get_positions — wszystkie otwarte pozycje
3. get_orders (status=open) — wiszące zlecenia

Oblicz dla każdej pozycji:
- wartość w USD
- % portfela
- unrealized P&L w USD i %

Oblicz flagi koncentracji (v2.0 risk-on):
- Single ticker > 40% equity → flag `concentration_per_ticker`
- Single trade size > 20% equity → flag `oversized_trade`
- Daily P&L < -12% → flag `daily_circuit_breaker`
- Weekly P&L < -25% → flag `weekly_circuit_breaker`
- Cash > 5% (idle capital) → flag `idle_cash` (informational)

## Format wyjścia

{
  "timestamp": "...",
  "equity": 105000,
  "cash": 12000,
  "cash_pct": 11.4,
  "positions": [
    {
      "symbol": "AAPL",
      "qty": 50,
      "market_value": 7500,
      "pct_of_portfolio": 7.1,
      "unrealized_pl_usd": 230,
      "unrealized_pl_pct": 3.2
    }
  ],
  "open_orders_count": 2,
  "flags": ["ewentualne ostrzeżenia"]
}
