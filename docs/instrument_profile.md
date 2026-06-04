# Instrument Profile (v3.15.0)

**Module:** `shared/instrument_profile.py`
**Audit-board feedback closed:** FB-001, FB-004
**Status:** shipped, tests green

## What it is

Per-symbol behavior profile computed from daily bars (free Alpaca IEX).
Answers the question "how does this instrument normally move?"

Profile includes:
- **VolatilityStats** — ATR(14)/price, daily range avg/max
- **GapStats** — open vs prior close, count of large gaps
- **WickStats** — upper/lower wick averages, long-wick ratio, reversal candle %
- **VolumeStats** — 20-bar average volume, recent spike ratio, low-volume days
- **TrendStats** — RSI(14), RSI distribution (oversold/neutral/overbought %), price vs MA20/MA50

## Quality score (most important field)

`profile.quality ∈ [0..1]`. Quality combines:
- sample-size score (≥60 bars excellent, ≥30 good, ≥10 minimum)
- freshness score (last bar within 1d = full; > 5d stale → penalty)
- component completeness (out of 5)

**A low quality profile MUST lower confidence.** Quality is never used to
raise confidence above what other data justifies.

## How it influences decisions

| Consumer | Effect |
|---|---|
| `confidence_builder.py` | low quality → `primary_score -= 0.03..0.05` |
| `liquidity_sweep_guard.py` | `wicks.long_wick_ratio > 25%` → flagged "trap-prone" historically |
| `position_manager.py` | volatility feeds time-stop / trailing decisions (future wiring) |
| `session_effectiveness.py` | per-symbol hit-rate calibration (future wiring) |

## Hard rules

- Profile NEVER bypasses risk engine.
- Profile NEVER emits a trade.
- Insufficient data → `quality=0.0` + `insufficient_data=True` → caller treats as missing.
- Failure to fetch bars → empty profile (no crash).

## What it does NOT include

- **Pre-market behavior** — see `pre_open_behavior.py` (paid SIP feed required for real data; interface only on free tier).
- **Intraday microstructure** — see `intraday_trend.py` (5-min bars from regular session only).
- **Cross-asset correlations** — see `lead_lag_analyzer.py`.

## Usage

```python
from instrument_profile import profile_symbol, DynamicInstrumentProfiler

# One-shot
p = profile_symbol("AAPL", days=60)
if p.insufficient_data:
    pass  # caller degrades confidence
else:
    atr = p.volatility.atr_pct_14
    rsi = p.trend.rsi_14
    long_wick_history = p.wicks.long_wick_ratio
```

```python
# On-demand from a monitor
profiler = DynamicInstrumentProfiler(days=60)
p = profiler.profile("NVDA", reason="momentum_long_candidate")
```

## Cost

$0/month. Uses Alpaca IEX free feed. In-process cache (TTL 5 min) so
repeated calls within one cron tick are free.

## Tests

`tests/test_feedback_v3150.py::TestInstrumentProfile` — 5 tests:
- insufficient bars → quality 0
- empty bars → "no_bars" warning
- full bars → quality > 0
- profile cannot raise confidence on its own
- dynamic profiler insufficient data path
