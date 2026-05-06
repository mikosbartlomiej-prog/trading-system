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
