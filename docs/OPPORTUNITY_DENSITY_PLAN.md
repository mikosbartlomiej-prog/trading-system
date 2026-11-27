# Opportunity Density Plan (v3.27.0)

**Generated:** `2026-11-27T14:11:54.647003+00:00`
**As of:** `2026-11-27T14:11:54.498342+00:00`
**Git HEAD:** `24d47a4fa9d0bbf121c02f7cd405d3dbb01904ac`

> Reporter NEVER recommends auto-lowering thresholds. NEVER recommends
> enabling broker / paper / live. NEVER promises profit. NEVER counts
> replay / near-miss / shadow records as paper edge. Every row carries
> an explicit `advisory_note` reaffirming the operator-review framing.

## A. Strategies closest to firing (top 5)

| Strategy | Replay candidates | Near-miss rate | Signals fired | Recommendation | Realism |
|---|---|---|---|---|---|
| `crypto-momentum` | 0 | 0.1289 | 48 | `KEEP` | `REALISTIC` |
| `crypto-oversold-bounce` | 0 | 0.0 | 310 | `REPLAY_TEST_VARIANT` | `TOO_LOOSE` |
| `momentum-long` | 0 | 0.0 | 0 | `OBSERVE_MORE` | `INSUFFICIENT_DATA` |
| `momentum-long-loose` | 0 | 0.0 | 0 | `OBSERVE_MORE` | `INSUFFICIENT_DATA` |
| `overbought-short` | 0 | 0.0 | 0 | `OBSERVE_MORE` | `INSUFFICIENT_DATA` |

## B. Symbols with most near-misses (top 10)

| Symbol | Near-miss count | Top strategy |
|---|---|---|
| `BCH/USD` | 3611 | `crypto-momentum` |
| `AVAX/USD` | 3191 | `crypto-momentum` |
| `AAVE/USD` | 3080 | `crypto-momentum` |
| `BTC/USD` | 3045 | `crypto-momentum` |
| `LINK/USD` | 2748 | `crypto-momentum` |
| `ETH/USD` | 2728 | `crypto-momentum` |
| `LTC/USD` | 2707 | `crypto-momentum` |
| `UNI/USD` | 2668 | `crypto-momentum` |
| `SOL/USD` | 2645 | `crypto-momentum` |
| `DOT/USD` | 2633 | `crypto-momentum` |

## C. Variants worth observing (top 5 from quarantine)

| Variant | Strategy | Status | Days observed |
|---|---|---|---|
| `crypto-momentum--rsi_threshold_55` | `crypto-momentum` | `QUARANTINED` | 0 |
| `crypto-momentum--24h_bracket_relaxed_2pct` | `crypto-momentum` | `QUARANTINED` | 0 |
| `crypto-oversold-bounce--rsi_threshold_33` | `crypto-oversold-bounce` | `QUARANTINED` | 0 |
| `momentum-long--breakout_threshold_1_5pct` | `momentum-long` | `QUARANTINED` | 0 |

> Quarantined variants are NEVER promoted to active runtime by this
> reporter. They are surfaced for observation only.

## D. Monitors needing diagnostic attention (WIRED_BUT_NOT_FIRING)

| Monitor | Status | RAN | Signals | Note |
|---|---|---|---|---|
| (none) | | | | |

## E. Universe changes (observe-only adds, NO trade-eligible promotion)

**Observe-only additions** (NEVER trade-eligible):

| Symbol | Asset class | Recommendation |
|---|---|---|
| (none) | | |

**Operator-review remove candidates:**

| Symbol | Recommendation |
|---|---|
| `SPY` | `REMOVE_LOW_QUALITY` |
| `QQQ` | `REMOVE_LOW_QUALITY` |
| `GLD` | `REMOVE_LOW_QUALITY` |
| `AMD` | `REMOVE_LOW_QUALITY` |
| `CRWD` | `REMOVE_LOW_QUALITY` |
| `NOW` | `REMOVE_LOW_QUALITY` |
| `PANW` | `REMOVE_LOW_QUALITY` |
| `ORCL` | `REMOVE_LOW_QUALITY` |

## F. Thresholds for operator review (top 3 by TOO_STRICT vote)

| Strategy | Metric | Threshold | Realism | Hit rate | Near-miss rate | Sample |
|---|---|---|---|---|---|---|
| `crypto-oversold-bounce` | `rsi` | 30.0 | `TOO_LOOSE` | 1.0 | 0.0 | 310 |

> This reporter NEVER auto-lowers any threshold — it surfaces the
> three most-blocked thresholds and asks the operator to review them.

## G. Data collection plan (next 7 / 14 / 30 days)

**Global snapshot:**

- Production positive rows: `179`
- Replay positive rows: `0`
- Near-miss rows (7d): `29560`
- Outcomes available: `False`
- Verdict (v3.27): `NOT_READY_NO_OUTCOMES`

**Per-strategy ETA estimates:**

| Strategy | Sample | ETA band | Evaluations | Signals fired |
|---|---|---|---|---|
| `crypto-oversold-bounce` | 310 | `30d_full_review` | 310 | 310 |
| `crypto-momentum` | 18110 | `30d_full_review` | 18110 | 48 |
| `momentum-long` | 0 | `7d_minimum` | 0 | 0 |
| `momentum-long-loose` | 0 | `7d_minimum` | 0 | 0 |
| `overbought-short` | 0 | `7d_minimum` | 0 | 0 |

## Safety contract

- Reporter NEVER imports `alpaca_orders`.
- Reporter NEVER makes a network call.
- Reporter NEVER auto-lowers any threshold.
- Reporter NEVER enables broker / paper / live execution paths.
- Reporter NEVER promises profit.
- Reporter NEVER promotes a quarantined variant to active runtime.
- Reporter NEVER counts replay/near-miss/shadow rows as paper edge.

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `DENSITY_PLAN_NEVER_LOWERS_THRESHOLDS`
- `DENSITY_PLAN_NEVER_PROMISES_PROFIT`
- `DENSITY_PLAN_NEVER_PROMOTES_VARIANTS`
- `DENSITY_PLAN_NEVER_ENABLES_BROKER`
- `REPLAY_NEVER_COUNTS_AS_PAPER_EDGE`
- `NEAR_MISS_NEVER_COUNTS_AS_PAPER_EDGE`
- `SHADOW_NEVER_COUNTS_AS_PAPER_EDGE`
