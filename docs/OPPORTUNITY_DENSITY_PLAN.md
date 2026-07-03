# Opportunity Density Plan (v3.27.0)

**Generated:** `2026-07-03T07:46:28.147306+00:00`
**As of:** `2026-07-03T07:46:28.007499+00:00`
**Git HEAD:** `05143a538d8779d37e723037fd362094f07e857a`

> Reporter NEVER recommends auto-lowering thresholds. NEVER recommends
> enabling broker / paper / live. NEVER promises profit. NEVER counts
> replay / near-miss / shadow records as paper edge. Every row carries
> an explicit `advisory_note` reaffirming the operator-review framing.

## A. Strategies closest to firing (top 5)

| Strategy | Replay candidates | Near-miss rate | Signals fired | Recommendation | Realism |
|---|---|---|---|---|---|
| `crypto-momentum` | 0 | 0.1603 | 26 | `KEEP` | `REALISTIC` |
| `crypto-oversold-bounce` | 0 | 0.0 | 256 | `REPLAY_TEST_VARIANT` | `TOO_LOOSE` |
| `momentum-long` | 0 | 0.0 | 0 | `OBSERVE_MORE` | `INSUFFICIENT_DATA` |
| `momentum-long-loose` | 0 | 0.0 | 0 | `OBSERVE_MORE` | `INSUFFICIENT_DATA` |
| `overbought-short` | 0 | 0.0 | 0 | `OBSERVE_MORE` | `INSUFFICIENT_DATA` |

## B. Symbols with most near-misses (top 10)

| Symbol | Near-miss count | Top strategy |
|---|---|---|
| `UNI/USD` | 3182 | `crypto-momentum` |
| `LINK/USD` | 3132 | `crypto-momentum` |
| `BTC/USD` | 3019 | `crypto-momentum` |
| `ETH/USD` | 2928 | `crypto-momentum` |
| `AVAX/USD` | 2586 | `crypto-momentum` |
| `AAVE/USD` | 2504 | `crypto-momentum` |
| `BCH/USD` | 2380 | `crypto-momentum` |
| `LTC/USD` | 2352 | `crypto-momentum` |
| `SOL/USD` | 2006 | `crypto-momentum` |
| `DOT/USD` | 1703 | `crypto-momentum` |

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
| `crypto-oversold-bounce` | `rsi` | 30.0 | `TOO_LOOSE` | 1.0 | 0.0 | 256 |

> This reporter NEVER auto-lowers any threshold — it surfaces the
> three most-blocked thresholds and asks the operator to review them.

## G. Data collection plan (next 7 / 14 / 30 days)

**Global snapshot:**

- Production positive rows: `147`
- Replay positive rows: `0`
- Near-miss rows (7d): `26224`
- Outcomes available: `False`
- Verdict (v3.27): `NOT_READY_NO_OUTCOMES`

**Per-strategy ETA estimates:**

| Strategy | Sample | ETA band | Evaluations | Signals fired |
|---|---|---|---|---|
| `crypto-oversold-bounce` | 256 | `30d_full_review` | 256 | 256 |
| `crypto-momentum` | 18215 | `30d_full_review` | 18215 | 26 |
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
