> INCIDENT ACTIVE: `AVAX` (and 4 more) in BROKER_REPAIR_REQUIRED state.
>
> Blocked symbols: `AVAX`, `AVAXUSD`, `ETH`, `ETHUSD`, `LTCUSD`
> Discovery layer remains active for analysis but trading is BLOCKED until manual repair.
> Status: DISCOVERY_ACTIVE_BUT_TRADING_BLOCKED_BY_P13
> See: [docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md](docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md)

# Opportunity Density Plan (v3.27.0)

**Generated:** `2026-06-16T09:40:08.495416+00:00`
**As of:** `2026-06-16T09:40:08.438511+00:00`
**Git HEAD:** `5d493ee95ba682d032a8c55b16cb9b0f321c2280`

> Reporter NEVER recommends auto-lowering thresholds. NEVER recommends
> enabling broker / paper / live. NEVER promises profit. NEVER counts
> replay / near-miss / shadow records as paper edge. Every row carries
> an explicit `advisory_note` reaffirming the operator-review framing.

## A. Strategies closest to firing (top 5)

| Strategy | Replay candidates | Near-miss rate | Signals fired | Recommendation | Realism |
|---|---|---|---|---|---|
| `crypto-momentum` | 0 | 0.1568 | 124 | `KEEP` | `REALISTIC` |
| `crypto-oversold-bounce` | 0 | 0.0 | 46 | `OBSERVE_MORE` | `TOO_LOOSE` |
| `momentum-long` | 0 | 0.0 | 0 | `OBSERVE_MORE` | `INSUFFICIENT_DATA` |
| `momentum-long-loose` | 0 | 0.0 | 0 | `OBSERVE_MORE` | `INSUFFICIENT_DATA` |
| `overbought-short` | 0 | 0.0 | 0 | `OBSERVE_MORE` | `INSUFFICIENT_DATA` |

## B. Symbols with most near-misses (top 10)

| Symbol | Near-miss count | Top strategy |
|---|---|---|
| `BTC/USD` | 1583 | `crypto-momentum` |
| `LTC/USD` | 1417 | `crypto-momentum` |
| `AAVE/USD` | 1337 | `crypto-momentum` |
| `AVAX/USD` | 1263 | `crypto-momentum` |
| `SOL/USD` | 1245 | `crypto-momentum` |
| `LINK/USD` | 1136 | `crypto-momentum` |
| `ETH/USD` | 1120 | `crypto-momentum` |
| `DOT/USD` | 1077 | `crypto-momentum` |
| `BCH/USD` | 945 | `crypto-momentum` |
| `UNI/USD` | 921 | `crypto-momentum` |

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
| `crypto-oversold-bounce` | `rsi` | 30.0 | `TOO_LOOSE` | 1.0 | 0.0 | 46 |

> This reporter NEVER auto-lowers any threshold — it surfaces the
> three most-blocked thresholds and asks the operator to review them.

## G. Data collection plan (next 7 / 14 / 30 days)

**Global snapshot:**

- Production positive rows: `0`
- Replay positive rows: `0`
- Near-miss rows (7d): `12332`
- Outcomes available: `False`
- Verdict (v3.27): `READY_FOR_COMPONENT_VARIANCE_REVIEW`

**Per-strategy ETA estimates:**

| Strategy | Sample | ETA band | Evaluations | Signals fired |
|---|---|---|---|---|
| `crypto-oversold-bounce` | 46 | `30d_full_review` | 46 | 46 |
| `crypto-momentum` | 15994 | `30d_full_review` | 15996 | 124 |
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
