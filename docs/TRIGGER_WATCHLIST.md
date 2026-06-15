# Trigger watchlist (v3.26.0)

**Generated:** `2026-06-15T14:33:31.645966+00:00`
**As of:** `2026-06-15T14:33:31.645611+00:00`
**Top-N:** 20
**Total rows:** 0

## Watchlist

| Strategy | Symbol | Asset | Distance | Near-history | Replay-cands | Trigger | Required movement | Mode | Status |
|---|---|---|---|---|---|---|---|---|---|
| (no candidates yet — replay/near-miss data empty) | | | | | | | | | |

## Preconditions (must hold before promotion)

- **Confidence:** confidence_score in [0.50, 0.85]; data_quality components fresh; system_health components fresh
- **Risk:** daily drawdown not tripped; VIX < 35; defensive_mode not armed; concentration cap not breached; per-strategy cooldown clear

## Safety contract

- Every row mode = `SHADOW_ONLY`.
- Every row status = `WATCHING`.
- This watchlist NEVER places orders.
- This watchlist NEVER auto-promotes a row.
- This script NEVER imports `alpaca_orders`.
- This script NEVER makes network calls.

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `WATCHLIST_NEVER_PLACES_ORDERS`
- `WATCHLIST_NEVER_AUTO_PROMOTES`
