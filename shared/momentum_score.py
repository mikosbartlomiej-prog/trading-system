"""
shared/momentum_score.py — Composite relative-strength scoring.

score_symbol(ticker, bars, spy_bars=None, qqq_bars=None) returns a
score in roughly [-1, +1] combining:

  momentum_5d, momentum_10d, momentum_20d
  relative_strength_vs_spy        (cumulative excess return 20d)
  relative_strength_vs_qqq        (cumulative excess return 20d)
  volume_expansion                (today vol / 20d avg)
  breakout_flag                   (close > yesterday's high OR 30-min ORH)
  trend_filter                    (price > SMA20 > SMA50)
  volatility_penalty              (high ATR / SMA20 ratio without trend = noise)

Weights come from config/aggressive_profile.json::scoring.weights.

Used by:
  - price-monitor pre-ranking (skan top_n_picks tickers per cron)
  - entry filter (min_score_for_entry gate)
  - LLM Curator payload (Curator widzi score per candidate)

Score components individually clipped to [-1, 1] before weighted sum.
Final score clipped to [-1, 1].
"""

from typing import Dict, List


def _pct(end: float, start: float) -> float:
    """Percent change start → end, safe on zero."""
    if not start:
        return 0.0
    return (end - start) / start


def _sma(values: List[float], window: int) -> float | None:
    """Simple moving average over last `window` values; None if insufficient."""
    if len(values) < window or window <= 0:
        return None
    return sum(values[-window:]) / window


def _atr(highs: List[float], lows: List[float], closes: List[float],
         period: int = 14) -> float | None:
    """ATR(14)."""
    n = len(closes)
    if n < period + 1:
        return None
    trs = []
    for i in range(n - period, n):
        if i == 0:
            continue
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return sum(trs) / len(trs) if trs else None


def _momentum(closes: List[float], lookback: int) -> float | None:
    """% return over `lookback` bars; None if not enough."""
    if len(closes) < lookback + 1:
        return None
    return _pct(closes[-1], closes[-1 - lookback])


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _relative_strength(asset_closes: List[float], bench_closes: List[float],
                        lookback: int = 20) -> float | None:
    """
    Cumulative excess return of asset over benchmark, last `lookback` bars.
    Positive = asset outperforming. None if insufficient data on either side.
    """
    a = _momentum(asset_closes, lookback)
    b = _momentum(bench_closes, lookback)
    if a is None or b is None:
        return None
    return a - b


def score_symbol(ticker: str,
                  bars: Dict[str, List[float]],
                  spy_bars: Dict[str, List[float]] | None = None,
                  qqq_bars: Dict[str, List[float]] | None = None,
                  intraday_orh: float | None = None) -> dict:
    """
    Compute composite momentum/RS score for `ticker`.

    `bars` shape (same as shared.market_data.get_daily_bars):
      {"close": [...], "high": [...], "low": [...], "open": [...],
       "volume": [...], "time": [...]}

    `spy_bars`, `qqq_bars`: optional benchmark bars for RS.
    `intraday_orh`: optional Opening Range High (30-min) — if today's
                    close > orh, breakout_flag credited; else falls back
                    to "close > prev day high" check.

    Returns:
      {
        "ticker": "NVDA",
        "score": 0.62,        # weighted sum, clipped [-1, 1]
        "components": {       # raw normalized components
          "momentum_5d":        +0.04,
          "momentum_10d":       +0.08,
          "momentum_20d":       +0.14,
          "relative_strength":  +0.06,
          "volume_expansion":   1.42,
          "breakout_flag":      1.0,
          "trend_filter":       1.0,
          "volatility_penalty": 0.0,
        },
        "atr_pct":              0.025,   # ATR / SMA20 for diagnostic
        "tradeable":            True,    # score >= profile.min_score_for_entry
        "reason":               "long_setup: mom20=+14%, RS=+6%, vol 1.4×, breakout"
      }

    All components individually clipped to [-1, 1] before weighted sum.
    Returns score=0.0 + reason="insufficient_data" on missing inputs.
    """
    closes = bars.get("close") or []
    highs  = bars.get("high")  or []
    lows   = bars.get("low")   or []
    volumes = bars.get("volume") or []

    if len(closes) < 22:
        return {
            "ticker":   ticker,
            "score":    0.0,
            "components": {},
            "tradeable": False,
            "reason":   "insufficient_data",
        }

    # Lazy import to avoid hard dep
    try:
        from profile import profile_value
    except ImportError:
        try:
            from shared.profile import profile_value
        except ImportError:
            def profile_value(_p, default=None): return default

    weights = profile_value("scoring.weights", {}) or {}
    min_score = float(profile_value("scoring.min_score_for_entry", 0.35))

    # ── Components ────────────────────────────────────────────────────
    mom_5d  = _momentum(closes, 5)  or 0.0
    mom_10d = _momentum(closes, 10) or 0.0
    mom_20d = _momentum(closes, 20) or 0.0

    rs_spy = _relative_strength(closes, (spy_bars or {}).get("close") or [])
    rs_qqq = _relative_strength(closes, (qqq_bars or {}).get("close") or [])
    # Use stronger of the two (we want leadership signal)
    rs = max([x for x in (rs_spy, rs_qqq) if x is not None], default=0.0)

    avg_vol_20 = _sma(volumes[:-1], 20) or 0.0   # exclude today
    vol_expansion = (volumes[-1] / avg_vol_20) if avg_vol_20 > 0 else 1.0

    # Breakout: close > intraday_orh if provided, else close > prev day high
    if intraday_orh is not None and intraday_orh > 0:
        breakout = 1.0 if closes[-1] > intraday_orh else 0.0
    else:
        prev_high = highs[-2] if len(highs) >= 2 else closes[-1]
        breakout = 1.0 if closes[-1] > prev_high else 0.0

    # Trend filter: price > SMA20 > SMA50
    sma20 = _sma(closes, 20) or 0.0
    sma50 = _sma(closes, 50) or 0.0
    if sma20 > 0 and sma50 > 0:
        trend = 1.0 if (closes[-1] > sma20 > sma50) else (
            -1.0 if (closes[-1] < sma20 < sma50) else 0.0
        )
    else:
        trend = 0.0

    # Volatility penalty: high ATR relative to SMA20 without trend
    atr = _atr(highs, lows, closes, 14)
    atr_pct = (atr / sma20) if (atr and sma20 > 0) else 0.0
    vol_penalty = atr_pct if (trend == 0 and atr_pct > 0.04) else 0.0   # high noise, no direction

    # ── Normalize to [-1, 1] ──────────────────────────────────────────
    # Momentums: clip at ±20% (=±1.0). 10% move → 0.5.
    mom_5d_n  = _clip(mom_5d  * 5)
    mom_10d_n = _clip(mom_10d * 3)
    mom_20d_n = _clip(mom_20d * 2)
    rs_n      = _clip(rs      * 5)
    # Volume: 1× = 0; 2× = +0.5; 3× = +1.0
    vol_n     = _clip((vol_expansion - 1.0) / 2.0)
    # breakout / trend already 0/1/-1
    breakout_n = _clip(breakout)
    trend_n    = _clip(trend)
    # Penalty: 5% ATR/SMA20 = -1.0
    vol_pen_n = _clip(-vol_penalty * 20)

    components = {
        "momentum_5d":        mom_5d_n,
        "momentum_10d":       mom_10d_n,
        "momentum_20d":       mom_20d_n,
        "relative_strength":  rs_n,
        "volume_expansion":   vol_n,
        "breakout_flag":      breakout_n,
        "trend_filter":       trend_n,
        "volatility_penalty": vol_pen_n,
    }

    # ── Weighted sum ──────────────────────────────────────────────────
    score = 0.0
    for k, v in components.items():
        w = float(weights.get(k, 0.0))
        score += w * v
    score = _clip(score)

    # ── Reason string ─────────────────────────────────────────────────
    reason_parts = []
    if mom_20d > 0.05:
        reason_parts.append(f"mom20=+{mom_20d*100:.1f}%")
    elif mom_20d < -0.05:
        reason_parts.append(f"mom20={mom_20d*100:.1f}%")
    if rs > 0.03:
        reason_parts.append(f"RS=+{rs*100:.1f}%")
    elif rs < -0.03:
        reason_parts.append(f"RS={rs*100:.1f}%")
    if vol_expansion > 1.5:
        reason_parts.append(f"vol {vol_expansion:.1f}×")
    if breakout > 0.5:
        reason_parts.append("breakout")
    if trend > 0:
        reason_parts.append("uptrend")
    elif trend < 0:
        reason_parts.append("downtrend")
    if vol_pen_n < -0.2:
        reason_parts.append(f"noise (ATR {atr_pct*100:.1f}%)")
    setup_type = "long_setup" if score >= 0 else "short_setup"

    return {
        "ticker":     ticker,
        "score":      round(score, 3),
        "components": {k: round(v, 3) for k, v in components.items()},
        "atr_pct":    round(atr_pct, 4),
        "tradeable":  abs(score) >= min_score,
        "reason":     f"{setup_type}: {', '.join(reason_parts) if reason_parts else 'no clear signal'}",
    }


def rank_universe(universe: List[str],
                    bars_provider,
                    spy_bars: Dict[str, List[float]] | None = None,
                    qqq_bars: Dict[str, List[float]] | None = None,
                    top_n: int | None = None) -> List[dict]:
    """
    Score every ticker in `universe` and return list sorted by score descending.
    `bars_provider(symbol) -> bars_dict` is called once per symbol — caller
    decides whether to use Alpaca, cached bars, etc.

    Optional `top_n` truncates the result. Otherwise returns full ranking.
    """
    scored = []
    for sym in universe:
        try:
            bars = bars_provider(sym)
        except Exception as e:
            print(f"  rank_universe: {sym} bars error: {e}")
            continue
        if not bars:
            continue
        scored.append(score_symbol(sym, bars, spy_bars=spy_bars, qqq_bars=qqq_bars))
    scored.sort(key=lambda s: s["score"], reverse=True)
    if top_n:
        scored = scored[:top_n]
    return scored
