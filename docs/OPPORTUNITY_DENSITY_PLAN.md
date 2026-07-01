# Opportunity Density Plan (v3.27.0)

**Generated:** `2026-07-01T08:36:21.844008+00:00`
**As of:** `2026-07-01T08:36:21.705571+00:00`
**Git HEAD:** `f5d3e51ab0d8827da688523be7a8bc21f5f4a3be`

> Reporter NEVER recommends auto-lowering thresholds. NEVER recommends
> enabling broker / paper / live. NEVER promises profit. NEVER counts
> replay / near-miss / shadow records as paper edge. Every row carries
> an explicit `advisory_note` reaffirming the operator-review framing.

## A. Strategies closest to firing (top 5)

| Strategy | Replay candidates | Near-miss rate | Signals fired | Recommendation | Realism |
|---|---|---|---|---|---|
| `crypto-momentum` | 0 | 0.1238 | 0 | `SHADOW_VARIANT_REVIEW` | `REALISTIC` |
| `crypto-oversold-bounce` | 0 | 0.0 | 586 | `REPLAY_TEST_VARIANT` | `TOO_LOOSE` |
| `momentum-long` | 0 | 0.0 | 0 | `OBSERVE_MORE` | `INSUFFICIENT_DATA` |
| `momentum-long-loose` | 0 | 0.0 | 0 | `OBSERVE_MORE` | `INSUFFICIENT_DATA` |
| `overbought-short` | 0 | 0.0 | 0 | `OBSERVE_MORE` | `INSUFFICIENT_DATA` |

## B. Symbols with most near-misses (top 10)

| Symbol | Near-miss count | Top strategy |
|---|---|---|
| `LINK/USD` | 3363 | `crypto-momentum` |
| `ETH/USD` | 3192 | `crypto-momentum` |
| `AAVE/USD` | 2949 | `crypto-momentum` |
| `BTC/USD` | 2923 | `crypto-momentum` |
| `UNI/USD` | 2788 | `crypto-momentum` |
| `AVAX/USD` | 2680 | `crypto-momentum` |
| `BCH/USD` | 2544 | `crypto-momentum` |
| `LTC/USD` | 2445 | `crypto-momentum` |
| `DOT/USD` | 1912 | `crypto-momentum` |
| `SOL/USD` | 1893 | `crypto-momentum` |

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
| `crypto-oversold-bounce` | `rsi` | 30.0 | `TOO_LOOSE` | 1.0 | 0.0 | 586 |

> This reporter NEVER auto-lowers any threshold — it surfaces the
> three most-blocked thresholds and asks the operator to review them.

## G. Data collection plan (next 7 / 14 / 30 days)

**Global snapshot:**

- Production positive rows: `305`
- Replay positive rows: `0`
- Near-miss rows (7d): `27121`
- Outcomes available: `False`
- Verdict (v3.27): `NOT_READY_NO_OUTCOMES`

**Per-strategy ETA estimates:**

| Strategy | Sample | ETA band | Evaluations | Signals fired |
|---|---|---|---|---|
| `crypto-oversold-bounce` | 586 | `30d_full_review` | 586 | 586 |
| `crypto-momentum` | 18029 | `30d_full_review` | 18029 | 0 |
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
