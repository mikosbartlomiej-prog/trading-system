"""v3.15.0 (2026-06-04) — InstrumentProfile + DynamicInstrumentProfiler.

Closes audit-board feedback FB-001 + FB-004 (instrument behavior profiling).

WHY
---
Trader feedback: "you can build a profile of a stock — how it moves." System
currently treats every ticker uniformly via momentum_score / risk_officer /
confidence. Missing: per-symbol history-aware statistics that answer
"what does this name normally do?"

CONTRACT
--------
Pure, deterministic, fail-soft. Built only from daily bars (free Alpaca IEX).
Output is a frozen dataclass `InstrumentProfile` consumed by:
  - confidence_builder.py (quality reduces score when profile thin)
  - liquidity_sweep_guard (wick stats feed sweep detection)
  - position_manager (volatility feeds time-stop / trailing decision)
  - session_effectiveness (per-symbol hit-rate calibration)

NEVER:
  - emits a trade
  - raises an exception to the caller
  - mutates state
  - uses future data

SAFETY
------
1. Quality score [0..1] derived from sample size + freshness.
2. Insufficient data → InstrumentProfile(quality=0.0, insufficient_data=True).
3. Profile NEVER raises confidence score on its own — only contributes to
   reduction (low-quality profile = confidence component penalty).
4. Cached locally (in-process) with explicit TTL. No external state.

Usage
-----
    from instrument_profile import profile_symbol
    p = profile_symbol("AAPL")
    if p.insufficient_data:
        # caller treats as missing info — confidence component degrades
        ...
    else:
        atr_pct = p.volatility.atr_pct_14
        ...
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field, asdict
from typing import Any

# ─── Local imports (fail-soft) ────────────────────────────────────────────────

try:
    from market_data import get_daily_bars
except ImportError:
    try:
        from shared.market_data import get_daily_bars
    except ImportError:
        def get_daily_bars(symbol: str, days: int = 35):  # type: ignore
            return None


# ─── Tunables (all configurable; documented) ──────────────────────────────────

MIN_BARS_USABLE     = 10    # below this → quality = 0.0
MIN_BARS_GOOD       = 30    # at this → quality 0.6+
MIN_BARS_EXCELLENT  = 60    # at this → quality 1.0 ceiling
CACHE_TTL_SECONDS   = 300.0 # 5 min cache (one cron tick)
MAX_BAR_AGE_DAYS    = 5     # latest bar older than this → freshness penalty

# Module-level cache. Per-process. Cleared at GitHub Actions worker boot.
_CACHE: dict[str, tuple[float, "InstrumentProfile"]] = {}


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class VolatilityStats:
    """ATR + daily range statistics."""
    atr_pct_14:        float  # 14-period ATR / price (e.g. 0.025 = 2.5%)
    daily_range_avg:   float  # mean (high-low) / close
    daily_range_max:   float  # max single-day range
    bars_used:         int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class GapStats:
    """Open vs previous close behavior."""
    gap_avg_pct:           float  # mean |open - prev_close| / prev_close
    gap_up_count:          int
    gap_down_count:        int
    large_gap_count:       int    # |gap| > 2%
    bars_used:             int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class WickStats:
    """Long-wick + reversal-candle stats — feeds liquidity sweep guard."""
    upper_wick_avg_pct:    float  # mean upper_wick / body
    lower_wick_avg_pct:    float  # mean lower_wick / body
    long_wick_ratio:       float  # fraction of bars where wick > 2×body
    reversal_candle_pct:   float  # fraction of bars where close crosses prior high then closes lower (failed breakout)
    bars_used:             int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class VolumeStats:
    """Volume distribution."""
    volume_avg_20:         float
    volume_spike_ratio:    float  # max(vol_recent_5) / avg_vol_20
    low_volume_days_pct:   float  # fraction days where vol < 0.5 × avg
    bars_used:             int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TrendStats:
    """RSI + position vs moving averages."""
    rsi_14:                float | None
    rsi_distribution:      dict  # {"oversold_pct", "neutral_pct", "overbought_pct"}
    price_vs_ma20_pct:     float | None  # (close - sma20) / sma20
    price_vs_ma50_pct:     float | None
    bars_used:             int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class InstrumentProfile:
    """Aggregated behavior profile. Frozen / read-only.

    `quality` in [0..1] expresses how trustworthy the profile is. Callers
    must treat low quality as "limited information" and degrade confidence
    accordingly. Quality is NEVER used to raise confidence.
    """
    symbol:             str
    profile_at_iso:     str
    bars_count:         int
    insufficient_data:  bool
    quality:            float          # [0..1]
    last_bar_iso:       str | None
    volatility:         VolatilityStats | None
    gaps:               GapStats | None
    wicks:              WickStats | None
    volume:             VolumeStats | None
    trend:              TrendStats | None
    warnings:           tuple = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "symbol":             self.symbol,
            "profile_at_iso":     self.profile_at_iso,
            "bars_count":         self.bars_count,
            "insufficient_data":  self.insufficient_data,
            "quality":            self.quality,
            "last_bar_iso":       self.last_bar_iso,
            "volatility":         self.volatility.to_dict() if self.volatility else None,
            "gaps":               self.gaps.to_dict() if self.gaps else None,
            "wicks":              self.wicks.to_dict() if self.wicks else None,
            "volume":             self.volume.to_dict() if self.volume else None,
            "trend":              self.trend.to_dict() if self.trend else None,
            "warnings":           list(self.warnings),
        }


# ─── Pure computations (testable in isolation) ────────────────────────────────

def _atr_pct(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(closes)):
        h, l, c_prev = highs[i], lows[i], closes[i - 1]
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        trs.append(tr)
    atr = sum(trs[-period:]) / period if trs else 0.0
    return atr / closes[-1] if closes[-1] > 0 else 0.0


def _gap_stats(opens, closes) -> GapStats | None:
    """Open[i] vs Close[i-1]."""
    if len(closes) < 2:
        return None
    pct_gaps = []
    up, down, large = 0, 0, 0
    for i in range(1, len(closes)):
        prev_close = closes[i - 1]
        if prev_close <= 0:
            continue
        g = (opens[i] - prev_close) / prev_close
        pct_gaps.append(abs(g))
        if g > 0:
            up += 1
        elif g < 0:
            down += 1
        if abs(g) > 0.02:
            large += 1
    if not pct_gaps:
        return None
    return GapStats(
        gap_avg_pct=sum(pct_gaps) / len(pct_gaps),
        gap_up_count=up,
        gap_down_count=down,
        large_gap_count=large,
        bars_used=len(pct_gaps),
    )


def _wick_stats(opens, highs, lows, closes) -> WickStats | None:
    if len(closes) < 5:
        return None
    upper_pcts, lower_pcts = [], []
    long_wick_count, reversal_count = 0, 0
    for i in range(1, len(closes)):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        body = abs(c - o) or 1e-9
        body_low, body_high = min(o, c), max(o, c)
        up_wick = h - body_high
        lo_wick = body_low - l
        upper_pcts.append(up_wick / body)
        lower_pcts.append(lo_wick / body)
        if max(up_wick, lo_wick) > 2 * body:
            long_wick_count += 1
        # Reversal candle: today's high > prior high, but close < prior close
        if h > highs[i - 1] and c < closes[i - 1]:
            reversal_count += 1
    n = len(upper_pcts)
    if n == 0:
        return None
    return WickStats(
        upper_wick_avg_pct=sum(upper_pcts) / n,
        lower_wick_avg_pct=sum(lower_pcts) / n,
        long_wick_ratio=long_wick_count / n,
        reversal_candle_pct=reversal_count / n,
        bars_used=n,
    )


def _volume_stats(volumes) -> VolumeStats | None:
    if len(volumes) < 5:
        return None
    nonzero = [v for v in volumes if v > 0]
    if len(nonzero) < 5:
        return None
    last_20 = nonzero[-20:]
    avg = sum(last_20) / len(last_20)
    if avg <= 0:
        return None
    last_5 = nonzero[-5:]
    spike = max(last_5) / avg if avg > 0 else 0.0
    low_vol_days = sum(1 for v in nonzero if v < 0.5 * avg) / len(nonzero)
    return VolumeStats(
        volume_avg_20=avg,
        volume_spike_ratio=spike,
        low_volume_days_pct=low_vol_days,
        bars_used=len(nonzero),
    )


def _rsi_14(closes) -> float | None:
    if len(closes) < 15:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain = sum(gains[-14:]) / 14
    avg_loss = sum(losses[-14:]) / 14
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _rsi_distribution(closes) -> dict:
    """% of recent bars in oversold / neutral / overbought zones."""
    if len(closes) < 20:
        return {"oversold_pct": 0.0, "neutral_pct": 0.0, "overbought_pct": 0.0}
    rsi_history = []
    for i in range(15, len(closes) + 1):
        win = closes[:i]
        r = _rsi_14(win)
        if r is not None:
            rsi_history.append(r)
    if not rsi_history:
        return {"oversold_pct": 0.0, "neutral_pct": 0.0, "overbought_pct": 0.0}
    n = len(rsi_history)
    return {
        "oversold_pct":   sum(1 for r in rsi_history if r <= 30) / n,
        "neutral_pct":    sum(1 for r in rsi_history if 30 < r < 70) / n,
        "overbought_pct": sum(1 for r in rsi_history if r >= 70) / n,
    }


def _trend_stats(closes) -> TrendStats | None:
    if len(closes) < 15:
        return None
    rsi = _rsi_14(closes)
    rsi_dist = _rsi_distribution(closes)
    last = closes[-1]
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    ma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
    return TrendStats(
        rsi_14=rsi,
        rsi_distribution=rsi_dist,
        price_vs_ma20_pct=((last - ma20) / ma20) if ma20 else None,
        price_vs_ma50_pct=((last - ma50) / ma50) if ma50 else None,
        bars_used=len(closes),
    )


def _vol_stats(highs, lows, closes) -> VolatilityStats | None:
    if len(closes) < 15:
        return None
    atr = _atr_pct(highs, lows, closes, 14)
    ranges = []
    for i in range(len(closes)):
        if closes[i] > 0:
            ranges.append((highs[i] - lows[i]) / closes[i])
    if not ranges:
        return None
    return VolatilityStats(
        atr_pct_14=atr,
        daily_range_avg=sum(ranges) / len(ranges),
        daily_range_max=max(ranges),
        bars_used=len(closes),
    )


# ─── Quality scoring ──────────────────────────────────────────────────────────

def _compute_quality(bars_count: int, freshness_days: float | None,
                       components_present: int) -> float:
    """Combine sample size + freshness + component completeness.

    Returns [0..1]. Quality contributes to confidence ONLY as a degrader.
    """
    if bars_count < MIN_BARS_USABLE:
        return 0.0
    # Sample size component
    if bars_count >= MIN_BARS_EXCELLENT:
        size_score = 1.0
    elif bars_count >= MIN_BARS_GOOD:
        size_score = 0.6 + 0.4 * (bars_count - MIN_BARS_GOOD) / max(
            MIN_BARS_EXCELLENT - MIN_BARS_GOOD, 1)
    else:
        size_score = 0.3 + 0.3 * (bars_count - MIN_BARS_USABLE) / max(
            MIN_BARS_GOOD - MIN_BARS_USABLE, 1)
    # Freshness component
    if freshness_days is None:
        freshness_score = 0.5
    elif freshness_days <= 1:
        freshness_score = 1.0
    elif freshness_days <= MAX_BAR_AGE_DAYS:
        freshness_score = 1.0 - 0.5 * (freshness_days - 1) / max(MAX_BAR_AGE_DAYS - 1, 1)
    else:
        freshness_score = 0.3  # stale → penalty
    # Component-completeness — out of 5 (vol, gaps, wicks, volume, trend)
    completeness = components_present / 5.0
    # Weighted average (size dominant, freshness next, completeness last)
    return max(0.0, min(1.0, 0.5 * size_score + 0.3 * freshness_score + 0.2 * completeness))


# ─── Public API ───────────────────────────────────────────────────────────────

def build_profile_from_bars(symbol: str, bars: dict,
                              now_ts: float | None = None) -> InstrumentProfile:
    """Pure function — construct profile from a bars dict.

    `bars` shape (matches `market_data.get_daily_bars`):
      {"open":[...], "high":[...], "low":[...], "close":[...],
       "volume":[...], "time":[iso_str...]}

    `now_ts` allows determinism in tests (default = time.time()).
    """
    now_ts = now_ts if now_ts is not None else time.time()
    profile_at_iso = _ts_to_iso(now_ts)
    warnings: list[str] = []

    if not bars or not bars.get("close"):
        return InstrumentProfile(
            symbol=symbol, profile_at_iso=profile_at_iso,
            bars_count=0, insufficient_data=True, quality=0.0,
            last_bar_iso=None,
            volatility=None, gaps=None, wicks=None, volume=None, trend=None,
            warnings=("no_bars",),
        )

    opens   = list(bars.get("open")   or [])
    highs   = list(bars.get("high")   or [])
    lows    = list(bars.get("low")    or [])
    closes  = list(bars.get("close")  or [])
    volumes = list(bars.get("volume") or [])
    times   = list(bars.get("time")   or [])

    bars_count = len(closes)
    if bars_count < MIN_BARS_USABLE:
        return InstrumentProfile(
            symbol=symbol, profile_at_iso=profile_at_iso,
            bars_count=bars_count, insufficient_data=True, quality=0.0,
            last_bar_iso=times[-1] if times else None,
            volatility=None, gaps=None, wicks=None, volume=None, trend=None,
            warnings=("insufficient_bars",),
        )

    # Compute components — each is fail-soft, returns None on its own threshold
    vol  = _vol_stats(highs, lows, closes)
    gaps = _gap_stats(opens, closes)
    wicks = _wick_stats(opens, highs, lows, closes)
    volume = _volume_stats(volumes)
    trend  = _trend_stats(closes)
    components_present = sum(1 for c in (vol, gaps, wicks, volume, trend) if c)

    if components_present == 0:
        warnings.append("all_components_failed")

    # Freshness
    freshness_days: float | None = None
    if times:
        try:
            # bars use 'time' from market_data with ISO strings
            from datetime import datetime, timezone
            last_dt = datetime.fromisoformat(str(times[-1]).replace("Z", "+00:00"))
            now_dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
            freshness_days = max(0.0, (now_dt - last_dt).total_seconds() / 86400.0)
            if freshness_days > MAX_BAR_AGE_DAYS:
                warnings.append(f"stale_bar_{freshness_days:.1f}d")
        except Exception:
            warnings.append("freshness_parse_error")

    quality = _compute_quality(bars_count, freshness_days, components_present)

    insufficient = (bars_count < MIN_BARS_USABLE) or (components_present == 0)

    return InstrumentProfile(
        symbol=symbol, profile_at_iso=profile_at_iso,
        bars_count=bars_count, insufficient_data=insufficient, quality=quality,
        last_bar_iso=times[-1] if times else None,
        volatility=vol, gaps=gaps, wicks=wicks, volume=volume, trend=trend,
        warnings=tuple(warnings),
    )


def profile_symbol(symbol: str, days: int = 60,
                    bypass_cache: bool = False,
                    now_ts: float | None = None) -> InstrumentProfile:
    """Fetch bars + build profile. Fail-soft cached entry point.

    Caches per-process for CACHE_TTL_SECONDS. Caller passing `bypass_cache=True`
    forces re-fetch (useful for tests + dynamic profiler).
    """
    now_ts = now_ts if now_ts is not None else time.time()
    cache_key = f"{symbol}|{days}"
    if not bypass_cache:
        hit = _CACHE.get(cache_key)
        if hit and (now_ts - hit[0]) < CACHE_TTL_SECONDS:
            return hit[1]

    try:
        bars = get_daily_bars(symbol, days=days)
    except Exception:
        bars = None

    profile = build_profile_from_bars(symbol, bars or {}, now_ts=now_ts)
    _CACHE[cache_key] = (now_ts, profile)
    return profile


def clear_cache() -> None:
    """Test hook + manual flush."""
    _CACHE.clear()


def _ts_to_iso(ts: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# ─── DynamicInstrumentProfiler — on-demand for monitor/strategy callers ───────

class DynamicInstrumentProfiler:
    """On-demand profile builder for monitors that select a ticker.

    Usage:
        profiler = DynamicInstrumentProfiler()
        p = profiler.profile("NVDA", reason="momentum_long_candidate")
        if p.insufficient_data:
            ...  # caller degrades confidence
        else:
            # use p.volatility.atr_pct_14 etc.
    """

    def __init__(self, days: int = 60):
        self.days = days
        self._call_log: list[tuple[str, str, float]] = []

    def profile(self, symbol: str, reason: str = "") -> InstrumentProfile:
        ts = time.time()
        p = profile_symbol(symbol, days=self.days, now_ts=ts)
        self._call_log.append((symbol, reason, p.quality))
        return p

    def call_log(self) -> list[tuple[str, str, float]]:
        return list(self._call_log)


__all__ = [
    "InstrumentProfile", "VolatilityStats", "GapStats", "WickStats",
    "VolumeStats", "TrendStats",
    "build_profile_from_bars", "profile_symbol", "clear_cache",
    "DynamicInstrumentProfiler",
    "MIN_BARS_USABLE", "MIN_BARS_GOOD", "MIN_BARS_EXCELLENT", "CACHE_TTL_SECONDS",
]
