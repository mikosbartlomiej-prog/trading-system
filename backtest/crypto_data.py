"""
v3.16 — Hourly crypto-bar fetcher for backtest harness.

Wraps Alpaca's v1beta3 /v1beta3/crypto/us/bars endpoint to pull a
configurable window of 1-hour candles. Returns bars in the same
parallel-list shape used by `backtest/data.py` so the downstream
`replay()` + `replay_with_realism()` and signal functions can be
asset-class-agnostic.

Why a separate module:
  - Daily stocks use /v2/stocks/{sym}/bars — different endpoint,
    different auth path (IEX feed flag), different symbol format.
  - Crypto symbols carry a slash ("BTC/USD"). The cache key needs
    sanitization.
  - We page through up to thousands of 1h bars (180 days × 24 = 4320
    bars; Alpaca returns 10k max per call but next_page_token makes
    this safe).

CONTRACT:
  fetch_hourly_crypto_bars(symbol, hours=4320) → dict | None

  Returns:
    {
      "close":  [floats],   # parallel lists, one entry per hour
      "high":   [floats],
      "low":    [floats],
      "open":   [floats],
      "volume": [floats],
      "time":   [iso8601 strings],
    }
  None on missing creds, HTTP error, or empty payload.

Fail-soft policy (paper-only system):
  - missing ALPACA_API_KEY / ALPACA_SECRET_KEY → return None, no raise
  - HTTP non-2xx → log, return None
  - empty bars array → return None
  - Json shape mismatch → catch, return None

Cache:
  Local JSONL/JSON files in backtest/cache/crypto/<sym>_<from>_<to>.json
  Date stamps in the cache key keep different windows isolated.
  No automatic invalidation — operator deletes cache to force refetch.
"""

from __future__ import annotations

import json
import os
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests


ALPACA_DATA_URL = "https://data.alpaca.markets"
CACHE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "cache", "crypto"
)

# Alpaca v1beta3 max bars per request. Documented 10,000; we use 10k.
_MAX_BARS_PER_PAGE = 10_000
# Defensive pagination cap (~21 days of 1h bars × MAX_PAGES would be many
# years — safe upper bound).
_MAX_PAGES = 100


def _cache_path(symbol: str, start_iso: str, end_iso: str) -> str:
    safe_sym = symbol.replace("/", "_")
    return os.path.join(
        CACHE_DIR,
        f"{safe_sym}_{start_iso[:10]}_{end_iso[:10]}.json",
    )


def _hours_to_window(hours: int) -> tuple[str, str]:
    """
    Return (start_iso, end_iso) for a `hours`-back window, rounded
    down to the hour. End is "now" rounded down so cache keys collapse
    across the same hour.
    """
    end_dt = datetime.now(timezone.utc).replace(
        minute=0, second=0, microsecond=0
    )
    start_dt = end_dt - timedelta(hours=hours)
    return (
        start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def fetch_hourly_crypto_bars(
    symbol: str,
    hours: int = 4320,
    *,
    use_cache: bool = True,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Optional[dict]:
    """
    Fetch 1-hour crypto bars from Alpaca v1beta3 for `symbol`.

    Args:
      symbol:   "BTC/USD", "ETH/USD", etc.
      hours:    how many hours of history to pull (default 4320 = 180 d).
                Ignored if `start` is provided.
      use_cache: read/write local JSON cache.
      start:    explicit ISO timestamp (overrides `hours`).
      end:      explicit ISO timestamp.

    Returns parallel-list dict or None on any failure (fail-soft).
    """
    # Resolve window
    if start and end:
        start_iso = start
        end_iso = end
    else:
        start_iso, end_iso = _hours_to_window(hours)

    os.makedirs(CACHE_DIR, exist_ok=True)
    cpath = _cache_path(symbol, start_iso, end_iso)

    if use_cache and os.path.exists(cpath):
        try:
            with open(cpath) as f:
                cached = json.load(f)
            # Sanity: cache must have the expected shape
            if cached and isinstance(cached, dict) and cached.get("close"):
                return cached
        except (json.JSONDecodeError, OSError):
            # Bad cache file — fall through to fetch
            pass

    api_key = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        print(f"  crypto_data: missing ALPACA creds for {symbol}")
        return None

    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    opens: list[float] = []
    volumes: list[float] = []
    times: list[str] = []

    page_token: Optional[str] = None
    pages = 0

    while True:
        pages += 1
        if pages > _MAX_PAGES:
            print(f"  crypto_data: pagination overflow for {symbol}")
            break

        params = {
            "symbols": symbol,
            "timeframe": "1Hour",
            "start": start_iso,
            "end": end_iso,
            "limit": _MAX_BARS_PER_PAGE,
            "sort": "asc",
        }
        if page_token:
            params["page_token"] = page_token

        try:
            r = requests.get(
                f"{ALPACA_DATA_URL}/v1beta3/crypto/us/bars",
                headers={
                    "APCA-API-KEY-ID": api_key,
                    "APCA-API-SECRET-KEY": secret_key,
                },
                params=params,
                timeout=30,
            )
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            print(f"  crypto_data fetch error {symbol}: {e}")
            return None

        # Alpaca response shape: {"bars": {"BTC/USD": [...]}, "next_page_token": ...}
        bars_root = payload.get("bars") if isinstance(payload, dict) else None
        bars_list = None
        if isinstance(bars_root, dict):
            # Try both with and without slash
            bars_list = bars_root.get(symbol) or bars_root.get(
                symbol.replace("/", "")
            )

        if not bars_list:
            # First page empty → genuine empty; subsequent page → just stop
            if pages == 1:
                print(f"  crypto_data: empty payload for {symbol}")
                return None
            break

        for b in bars_list:
            try:
                closes.append(float(b["c"]))
                highs.append(float(b["h"]))
                lows.append(float(b["l"]))
                opens.append(float(b["o"]))
                volumes.append(float(b["v"]))
                times.append(b["t"])
            except (KeyError, TypeError, ValueError) as e:
                # Skip malformed bar, keep going
                print(f"  crypto_data: malformed bar in {symbol}: {e}")
                continue

        page_token = (
            payload.get("next_page_token") if isinstance(payload, dict) else None
        )
        if not page_token:
            break
        _time.sleep(0.05)  # gentle pacing

    if not closes:
        return None

    bars = {
        "close": closes,
        "high": highs,
        "low": lows,
        "open": opens,
        "volume": volumes,
        "time": times,
    }

    if use_cache:
        try:
            with open(cpath, "w") as f:
                json.dump(bars, f)
        except OSError as e:
            print(f"  crypto_data: cache write failed for {symbol}: {e}")

    return bars


def hours_ago_window(hours: int) -> tuple[str, str]:
    """Helper for CLI: return (start_iso, end_iso) for the last `hours` window."""
    return _hours_to_window(hours)


__all__ = [
    "fetch_hourly_crypto_bars",
    "hours_ago_window",
    "CACHE_DIR",
]
