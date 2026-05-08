"""
Historical-bar fetcher for the backtest harness.

Wraps Alpaca's /v2/stocks/{sym}/bars endpoint to pull a configurable
window. Returns the same shape as `shared/market_data.get_daily_bars`
so the strategy functions in `strategies.py` are agnostic.

Caches results in `backtest/.cache/<sym>-<start>-<end>.json` so repeated
runs don't hammer Alpaca.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests


ALPACA_DATA_URL = "https://data.alpaca.markets"
CACHE_DIR       = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")


def _cache_path(symbol: str, start: str, end: str) -> str:
    safe_sym = symbol.replace("/", "_")
    return os.path.join(CACHE_DIR, f"{safe_sym}-{start}-{end}.json")


def fetch_daily_bars(symbol: str, start_date: str, end_date: str,
                      use_cache: bool = True) -> Optional[dict]:
    """
    Fetch daily bars from Alpaca for `symbol` between `start_date` and
    `end_date` (inclusive). Both dates as YYYY-MM-DD ISO strings.

    Returns dict with parallel lists:
      {close, high, low, open, volume, time}
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cpath = _cache_path(symbol, start_date, end_date)
    if use_cache and os.path.exists(cpath):
        with open(cpath) as f:
            return json.load(f)

    api_key    = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        print(f"  data: missing ALPACA creds for {symbol}")
        return None

    closes, highs, lows, opens, volumes, times = [], [], [], [], [], []
    page_token: Optional[str] = None
    pages = 0

    while True:
        pages += 1
        if pages > 100:
            print(f"  data: pagination overflow for {symbol}")
            break
        params = {
            "timeframe":  "1Day",
            "start":      start_date,
            "end":        end_date,
            "limit":      10000,
            "adjustment": "split",
            "feed":       "iex",
        }
        if page_token:
            params["page_token"] = page_token

        try:
            r = requests.get(
                f"{ALPACA_DATA_URL}/v2/stocks/{symbol}/bars",
                headers={
                    "APCA-API-KEY-ID":     api_key,
                    "APCA-API-SECRET-KEY": secret_key,
                },
                params=params,
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  data fetch error {symbol}: {e}")
            return None

        for b in data.get("bars") or []:
            closes.append(float(b["c"]))
            highs.append(float(b["h"]))
            lows.append(float(b["l"]))
            opens.append(float(b["o"]))
            volumes.append(float(b["v"]))
            times.append(b["t"])

        page_token = data.get("next_page_token")
        if not page_token:
            break
        time.sleep(0.05)

    if not closes:
        return None

    bars = {"close": closes, "high": highs, "low": lows,
            "open": opens, "volume": volumes, "time": times}

    if use_cache:
        with open(cpath, "w") as f:
            json.dump(bars, f)

    return bars


def date_range_days_ago(days: int) -> tuple[str, str]:
    """Helper: return (start_iso, end_iso) for the last `days` calendar days."""
    end   = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()
