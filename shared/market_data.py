"""
Daily-bar fetcher for entry monitors.

Uses Alpaca Market Data API (free IEX feed, same paper keys we already use).
Replaces Finnhub `/stock/candle`, which moved behind a paid plan in 2024 and
now returns 403 for free-tier keys.

The returned dict keeps the same shape the old Finnhub-based helper used,
so downstream RSI/ATR/volume code does not need to change.
"""

import os
import requests
from datetime import datetime, timedelta, timezone

ALPACA_DATA_URL = "https://data.alpaca.markets"


def get_daily_bars(symbol: str, days: int = 35) -> dict | None:
    """
    Fetch up to ~`days` trading days of daily bars for `symbol`.

    Returns dict with parallel lists:
      { close, high, low, open, volume, time }
    or None on missing creds / no data / API error.
    """
    api_key    = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        print(f"  bars: brak ALPACA creds dla {symbol}")
        return None

    # Buffer for weekends/holidays so we get at least `days` trading bars
    end   = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days * 2 + 5)

    try:
        r = requests.get(
            f"{ALPACA_DATA_URL}/v2/stocks/{symbol}/bars",
            headers={
                "APCA-API-KEY-ID":     api_key,
                "APCA-API-SECRET-KEY": secret_key,
            },
            params={
                "timeframe":  "1Day",
                "start":      start.isoformat(),
                "end":        end.isoformat(),
                "limit":      10000,
                "adjustment": "split",
                "feed":       "iex",
            },
            timeout=15,
        )
        r.raise_for_status()
        bars = r.json().get("bars", []) or []
    except Exception as e:
        print(f"  bars {symbol} error: {e}")
        return None

    if not bars:
        return None

    return {
        "close":  [float(b["c"]) for b in bars],
        "high":   [float(b["h"]) for b in bars],
        "low":    [float(b["l"]) for b in bars],
        "open":   [float(b["o"]) for b in bars],
        "volume": [float(b["v"]) for b in bars],
        "time":   [b["t"] for b in bars],
    }


# ─── Reaction metrics for event-probability scoring ───────────────────────────

# Module-level cache for one cron tick (each run is a fresh Python process,
# so this is naturally invalidated).
_REACTION_CACHE: dict[str, dict | None] = {}


def compute_reaction_metrics(symbol: str, lookback_days: int = 25) -> dict | None:
    """
    Real-bar inputs for shared.event_scoring.market_reaction().

    Returns:
      {
        "price_move_atr": |today_close - prev_close| / ATR(14),
        "volume_ratio":   today_volume / 20d avg volume (excl today),
        "gap_pct":        (today_open - prev_close) / prev_close * 100,
        "atr":            ATR(14) for context,
        "today_close":    today_close for context,
      }

    Returns None when:
      - missing creds / API failure
      - fewer than 16 daily bars available (need 14 for ATR + 2 for delta)
      - ATR <= 0 (illiquid / data quality issue)

    Callers must fall back to placeholder values (0.5, 1.0, 0.0) on None.
    Per-tick cached: repeated calls for the same symbol within one run are free.
    """
    if symbol in _REACTION_CACHE:
        return _REACTION_CACHE[symbol]

    bars = get_daily_bars(symbol, days=lookback_days)
    result: dict | None = None
    try:
        if bars and len(bars["close"]) >= 16:
            closes  = bars["close"]
            highs   = bars["high"]
            lows    = bars["low"]
            opens   = bars["open"]
            volumes = bars["volume"]

            # ATR(14): mean True Range across last 14 bars
            period = 14
            start  = max(1, len(closes) - period)
            trs    = []
            for i in range(start, len(closes)):
                tr = max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i-1]),
                    abs(lows[i]  - closes[i-1]),
                )
                trs.append(tr)
            atr = (sum(trs) / len(trs)) if trs else 0.0

            if atr > 0:
                today_close = closes[-1]
                prev_close  = closes[-2]
                today_open  = opens[-1]
                today_vol   = volumes[-1]

                price_move_atr = abs(today_close - prev_close) / atr

                # 20-day avg volume excluding today (so today doesn't skew the ratio)
                vol_window = volumes[-21:-1] if len(volumes) >= 21 else volumes[:-1]
                avg_volume = (sum(vol_window) / len(vol_window)) if vol_window else today_vol
                volume_ratio = (today_vol / avg_volume) if avg_volume > 0 else 1.0

                gap_pct = ((today_open - prev_close) / prev_close * 100.0) if prev_close > 0 else 0.0

                result = {
                    "price_move_atr": round(price_move_atr, 2),
                    "volume_ratio":   round(volume_ratio, 2),
                    "gap_pct":        round(gap_pct, 2),
                    "atr":            round(atr, 2),
                    "today_close":    round(today_close, 2),
                }
    except Exception as e:
        print(f"  reaction metrics {symbol} error: {e}")
        result = None

    _REACTION_CACHE[symbol] = result
    return result
