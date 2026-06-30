> INCIDENT ACTIVE: `AVAX/USD` (and 2 more) in BROKER_REPAIR_REQUIRED state.
>
> Blocked symbols: `AVAX/USD`, `ETH/USD`, `LTC/USD`
> Discovery layer remains active for analysis but trading is BLOCKED until manual repair.
> Status: DISCOVERY_ACTIVE_BUT_TRADING_BLOCKED_BY_P13
> See: [docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md](docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md)

# Trigger watchlist (v3.27.0)

**Generated:** `2026-06-30T08:07:06.838400+00:00`
**As of:** `2026-06-30T08:07:06.694286+00:00`
**Top-N:** 30
**Total rows:** 28

## Rows by priority

| Priority | Count |
|---|---|
| `P1` | 24 |
| `P2` | 4 |
| `P3` | 0 |
| `BLOCKED` | 0 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 11 |
| `crypto-oversold-bounce` | 11 |
| `overbought-short` | 6 |

## Watchlist (sorted by priority)

| Pri | Strategy | Symbol | Asset | Distance | NM_7d | ReplaySup | VariantSup | Required movement | Mode | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| **P1** | `crypto-momentum` | `ETH/USD` | crypto | 0.0006 | 3086 | no | — | 24h move in [3%, 15%] | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-momentum` | `LINK/USD` | crypto | 0.0006 | 3209 | no | — | 24h move in [3%, 15%] | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-momentum` | `AAVE/USD` | crypto | 0.0007 | 3035 | no | — | 24h move in [3%, 15%] | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-momentum` | `BTC/USD` | crypto | 0.0007 | 2757 | no | — | 24h move in [3%, 15%] | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-momentum` | `AVAX/USD` | crypto | 0.0008 | 2403 | no | — | 24h move in [3%, 15%] | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-momentum` | `LTC/USD` | crypto | 0.0008 | 2402 | no | — | 24h move in [3%, 15%] | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-momentum` | `UNI/USD` | crypto | 0.0008 | 2450 | no | — | 24h move in [3%, 15%] | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-momentum` | `BCH/USD` | crypto | 0.0009 | 2289 | no | — | 24h move in [3%, 15%] | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-momentum` | `DOT/USD` | crypto | 0.0010 | 2072 | no | — | 24h move in [3%, 15%] | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-momentum` | `SOL/USD` | crypto | 0.0011 | 1839 | no | — | 24h move in [3%, 15%] | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-oversold-bounce` | `LINK/USD` | crypto | 0.0086 | 230 | no | — | RSI(14) <= 30 + 3-bar stabilization | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-oversold-bounce` | `ETH/USD` | crypto | 0.0090 | 219 | no | — | RSI(14) <= 30 + 3-bar stabilization | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-oversold-bounce` | `AVAX/USD` | crypto | 0.0102 | 195 | no | — | RSI(14) <= 30 + 3-bar stabilization | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `overbought-short` | `AAPL` | us_equity | 0.0106 | 186 | no | — | RSI(14) > 72 + visible weakening | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-oversold-bounce` | `LTC/USD` | crypto | 0.0125 | 158 | no | — | RSI(14) <= 30 + 3-bar stabilization | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-oversold-bounce` | `BTC/USD` | crypto | 0.0139 | 142 | no | — | RSI(14) <= 30 + 3-bar stabilization | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-oversold-bounce` | `UNI/USD` | crypto | 0.0143 | 138 | no | — | RSI(14) <= 30 + 3-bar stabilization | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-oversold-bounce` | `BCH/USD` | crypto | 0.0152 | 130 | no | — | RSI(14) <= 30 + 3-bar stabilization | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-oversold-bounce` | `DOT/USD` | crypto | 0.0172 | 114 | no | — | RSI(14) <= 30 + 3-bar stabilization | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `overbought-short` | `META` | us_equity | 0.0182 | 108 | no | — | RSI(14) > 72 + visible weakening | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-oversold-bounce` | `AAVE/USD` | crypto | 0.0238 | 82 | no | — | RSI(14) <= 30 + 3-bar stabilization | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `overbought-short` | `AMZN` | us_equity | 0.0323 | 60 | no | — | RSI(14) > 72 + visible weakening | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `overbought-short` | `NVDA` | us_equity | 0.0323 | 60 | no | — | RSI(14) > 72 + visible weakening | **SHADOW_ONLY** | **WATCHING** |
| **P1** | `crypto-oversold-bounce` | `SOL/USD` | crypto | 0.0385 | 50 | no | — | RSI(14) <= 30 + 3-bar stabilization | **SHADOW_ONLY** | **WATCHING** |
| **P2** | `overbought-short` | `MSFT` | us_equity | 0.1000 | 18 | no | — | RSI(14) > 72 + visible weakening | **SHADOW_ONLY** | **WATCHING** |
| **P2** | `crypto-oversold-bounce` | `UNSPECIFIED` | us_equity | 0.1260 | 1244 | no | — | RSI(14) <= 30 + 3-bar stabilization | **SHADOW_ONLY** | **WATCHING** |
| **P2** | `crypto-momentum` | `UNSPECIFIED` | us_equity | 0.1450 | 21560 | no | — | 24h move in [3%, 15%] | **SHADOW_ONLY** | **WATCHING** |
| **P2** | `overbought-short` | `UNSPECIFIED` | us_equity | 0.1470 | 360 | no | — | RSI(14) > 72 + visible weakening | **SHADOW_ONLY** | **WATCHING** |

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
