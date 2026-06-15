# Trigger watchlist (v3.27.0)

**Generated:** `2026-06-15T15:20:44.724191+00:00`
**As of:** `2026-06-15T15:20:44.703688+00:00`
**Top-N:** 30
**Total rows:** 14

## Rows by priority

| Priority | Count |
|---|---|
| `P1` | 4 |
| `P2` | 6 |
| `P3` | 4 |
| `BLOCKED` | 0 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-oversold-bounce` | 8 |
| `crypto-momentum` | 5 |
| `overbought-short` | 1 |

## Watchlist (sorted by priority)

| Pri | Strategy | Symbol | Asset | Distance | NM_7d | ReplaySup | VariantSup | Required movement | Mode | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| **P1** | `crypto-momentum` | `AVAX/USD` | crypto | 0.0048 | 415 | no | — | 24h move in [3%, 15%] | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-momentum` | `LINK/USD` | crypto | 0.0056 | 357 | no | — | 24h move in [3%, 15%] | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-momentum` | `DOT/USD` | crypto | 0.0057 | 347 | no | — | 24h move in [3%, 15%] | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-momentum` | `UNI/USD` | crypto | 0.0133 | 294 | no | — | 24h move in [3%, 15%] | **SHADOW_ONLY** | **WATCHING** |
| **P2** | `crypto-oversold-bounce` | `UNSPECIFIED` | us_equity | 0.1111 | 141 | no | — | RSI(14) <= 30 + 3-bar stabilization | **SHADOW_ONLY** | **WATCHING** |
| **P2** | `crypto-oversold-bounce` | `LTC/USD` | crypto | 0.1176 | 15 | no | — | RSI(14) <= 30 + 3-bar stabilization | **SHADOW_ONLY** | **WATCHING** |
| **P2** | `crypto-oversold-bounce` | `UNI/USD` | crypto | 0.1333 | 13 | no | — | RSI(14) <= 30 + 3-bar stabilization | **SHADOW_ONLY** | **WATCHING** |
| **P2** | `crypto-oversold-bounce` | `LINK/USD` | crypto | 0.1379 | 21 | no | — | RSI(14) <= 30 + 3-bar stabilization | **SHADOW_ONLY** | **WATCHING** |
| **P2** | `crypto-momentum` | `UNSPECIFIED` | us_equity | 0.1433 | 3789 | no | — | 24h move in [3%, 15%] | **SHADOW_ONLY** | **WATCHING** |
| **P2** | `overbought-short` | `UNSPECIFIED` | us_equity | 0.1467 | 144 | no | — | RSI(14) > 72 + visible weakening | **SHADOW_ONLY** | **WATCHING** |
| **P3** | `crypto-oversold-bounce` | `AAVE/USD` | crypto | 0.2000 | 8 | no | — | RSI(14) <= 30 + 3-bar stabilization | **SHADOW_ONLY** | **WATCHING** |
| **P3** | `crypto-oversold-bounce` | `BCH/USD` | crypto | 0.2353 | 9 | no | — | RSI(14) <= 30 + 3-bar stabilization | **SHADOW_ONLY** | **WATCHING** |
| **P3** | `crypto-oversold-bounce` | `SOL/USD` | crypto | 0.2857 | 5 | no | — | RSI(14) <= 30 + 3-bar stabilization | **SHADOW_ONLY** | **WATCHING** |
| **P3** | `crypto-oversold-bounce` | `DOT/USD` | crypto | 0.3636 | 5 | no | — | RSI(14) <= 30 + 3-bar stabilization | **SHADOW_ONLY** | **WATCHING** |

## Priority rubric

- **P1** — `distance_to_trigger < 0.05` AND `near_miss_count_7d >= 3` AND risk clean.
- **P2** — `0.05 <= distance < 0.15` AND `near_miss_count_7d >= 1`.
- **P3** — `distance >= 0.15` (trending closer).
- **BLOCKED** — distance unknown OR risk preconditions failed OR data missing OR already in shadow queue.

## Preconditions (must hold before promotion)

- **Confidence:** confidence_score in [0.50, 0.85]; data_quality components fresh; system_health components fresh
- **Risk:** daily drawdown not tripped; VIX < 35; defensive_mode not armed; concentration cap not breached; per-strategy cooldown clear

## Safety contract

- Every row mode = `SHADOW_ONLY`.
- Every row status = `WATCHING`.
- This watchlist NEVER places orders.
- This watchlist NEVER auto-promotes a row.
- This watchlist NEVER auto-changes thresholds.
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
- `WATCHLIST_NEVER_AUTO_CHANGES_THRESHOLDS`
