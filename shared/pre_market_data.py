"""v3.16.0 (2026-06-04) — Pre-market data fetcher (FB-002 follow-up).

WHY
---
The v3.15.0 interface `shared/pre_open_behavior.py::analyze_pre_open` accepts
caller-supplied bars but had no free-tier data source wired. Trader feedback
question #3 (operator decision walkthrough 2026-06-04) opted in for the
Yahoo `v8/finance/chart` gray-zone path with a fallback to Nasdaq extended-
trading endpoint. This module provides BOTH sources, fail-soft, cached, no
paid services.

CONTRACT
--------
- Public API:
    fetch_pre_market_bars(symbol, lookback_minutes=60) -> list[bar_dict]
    fetch_pre_market_summary(symbol) -> dict | None
    get_pre_market_context(symbol) -> dict
- Bar shape MUST match analyze_pre_open expectations:
    {"o": float, "h": float, "l": float, "c": float, "v": float, "t": iso_str}
- Fail-soft: HTTP error, 429, timeout, malformed JSON, empty symbol → empty
  list / None / context-with-warnings. NEVER raises.
- In-process TTL cache (300s) per (symbol, endpoint).
- 10s HTTP timeout, custom User-Agent (no auth).

LIMITATIONS
-----------
- Yahoo `v8/finance/chart` is undocumented gray-zone. Yahoo can rate-limit
  or change response shape without notice. We catch all exceptions.
- Nasdaq `extended-trading` is also undocumented; same fail-soft contract.
- IEX (the Alpaca free feed) does NOT include pre-market — so we never go
  to Alpaca here. Previous-session close/high/low DO come from Alpaca
  daily bars via shared/market_data.get_daily_bars (already free).

RE-DECISION TRIGGERS
--------------------
- Yahoo HTTP 429 sustained → operator should consider switching to Nasdaq
  as primary, or paying for the SIP feed (currently rejected).
- Either source changes response shape → tests will fail next CI run.
- New free pre-market feed appears (e.g. Polygon free tier with PM bars)
  → add as Tier-0 source ahead of Yahoo.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

import requests


# ─── Constants ────────────────────────────────────────────────────────────────

USER_AGENT = "trading-system-paper/3.16 (mikosbartlomiej-prog/trading-system)"
HTTP_TIMEOUT_S = 10
CACHE_TTL_S = 300

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
NASDAQ_EXTENDED_URL = (
    "https://api.nasdaq.com/api/quote/{symbol}/extended-trading"
    "?assetclass=stocks&markettype=pre"
)


# ─── In-process cache ────────────────────────────────────────────────────────

# Module-level cache keyed by (symbol, endpoint) → (expires_epoch, payload)
_CACHE: dict[tuple[str, str], tuple[float, object]] = {}


def _cache_get(key: tuple[str, str]):
    entry = _CACHE.get(key)
    if not entry:
        return None
    expires, payload = entry
    if time.time() >= expires:
        # Expired – drop silently
        _CACHE.pop(key, None)
        return None
    return payload


def _cache_set(key: tuple[str, str], payload) -> None:
    _CACHE[key] = (time.time() + CACHE_TTL_S, payload)


def _clear_cache() -> None:
    """Test helper. Not part of public API."""
    _CACHE.clear()


# ─── Utility ──────────────────────────────────────────────────────────────────

def _safe_symbol(symbol: str | None) -> str:
    """Return a URL-encoded, trimmed symbol. Empty string means caller-blank."""
    if not symbol:
        return ""
    s = str(symbol).strip()
    if not s:
        return ""
    return quote_plus(s)


def _iso_utc(epoch_s: int | float) -> str:
    """Convert epoch seconds → UTC ISO string. Fail-soft → empty string."""
    try:
        dt = datetime.fromtimestamp(float(epoch_s), tz=timezone.utc)
        # Keep seconds precision; mirrors Alpaca bar shape style.
        return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    except Exception:
        return ""


def _http_get(url: str) -> tuple[int, object] | None:
    """Single HTTP GET that NEVER raises. Returns (status, json_obj) or None.

    None means transport-level failure (timeout, connection error, etc.).
    A returned tuple may still carry a non-200 status, which the caller
    interprets.
    """
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=HTTP_TIMEOUT_S,
        )
    except Exception:
        # Connection error, timeout, DNS failure, SSL, etc. → silent
        return None
    try:
        payload = resp.json()
    except Exception:
        payload = None
    return resp.status_code, payload


# ─── Yahoo ────────────────────────────────────────────────────────────────────

def _fetch_yahoo_bars(symbol_encoded: str) -> list[dict]:
    """Fetch pre-market 1-minute bars from Yahoo `v8/finance/chart`.

    Returns [] on failure. Pre-market is the segment marked
    `pre` in `meta.tradingPeriods.pre` for US equities; we filter the
    `timestamp` array by that window when available.
    """
    if not symbol_encoded:
        return []

    url = YAHOO_CHART_URL.format(symbol=symbol_encoded) + (
        "?interval=1m&range=1d&includePrePost=true"
    )

    got = _http_get(url)
    if got is None:
        return []

    status, payload = got
    if status != 200 or not isinstance(payload, dict):
        return []

    try:
        result = (payload.get("chart") or {}).get("result") or []
        if not result:
            return []
        r0 = result[0]
        timestamps = r0.get("timestamp") or []
        indicators = r0.get("indicators") or {}
        quote = (indicators.get("quote") or [{}])[0]
        opens   = quote.get("open")   or []
        highs   = quote.get("high")   or []
        lows    = quote.get("low")    or []
        closes  = quote.get("close")  or []
        volumes = quote.get("volume") or []

        meta = r0.get("meta") or {}
        trading_periods = meta.get("tradingPeriods") or {}
        # `pre` is list of [{"start": epoch, "end": epoch, ...}]
        pre_window: tuple[int, int] | None = None
        pre_list = trading_periods.get("pre") or []
        if isinstance(pre_list, list) and pre_list:
            # Yahoo nests as [[{...}]] sometimes.
            first = pre_list[0]
            if isinstance(first, list) and first:
                first = first[0]
            if isinstance(first, dict):
                start_ep = first.get("start")
                end_ep   = first.get("end")
                if isinstance(start_ep, (int, float)) and isinstance(end_ep, (int, float)):
                    pre_window = (int(start_ep), int(end_ep))

        bars: list[dict] = []
        n = min(
            len(timestamps), len(opens), len(highs),
            len(lows), len(closes), len(volumes),
        )
        for i in range(n):
            t = timestamps[i]
            if pre_window is not None:
                if not (pre_window[0] <= t <= pre_window[1]):
                    continue
            o, h, l, c, v = opens[i], highs[i], lows[i], closes[i], volumes[i]
            # Skip rows with None OHLC; Yahoo can sparsely fill.
            if o is None or h is None or l is None or c is None:
                continue
            try:
                bars.append({
                    "o": float(o),
                    "h": float(h),
                    "l": float(l),
                    "c": float(c),
                    "v": float(v if v is not None else 0.0),
                    "t": _iso_utc(t),
                })
            except Exception:
                continue
        return bars
    except Exception:
        return []


# ─── Nasdaq fallback ──────────────────────────────────────────────────────────

def _fetch_nasdaq_summary(symbol_encoded: str) -> dict | None:
    """Nasdaq summary fallback. Returns dict-of-fields or None on failure.

    Nasdaq's extended-trading endpoint returns a `data.lastSalePrice` style
    payload. We pass through whatever we get (after fail-soft parsing). The
    caller decides whether the summary is enough to use.
    """
    if not symbol_encoded:
        return None
    url = NASDAQ_EXTENDED_URL.format(symbol=symbol_encoded)
    got = _http_get(url)
    if got is None:
        return None
    status, payload = got
    if status != 200 or not isinstance(payload, dict):
        return None
    try:
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            return None
        return {
            "symbol":      payload.get("symbol") or "",
            "last_price":  data.get("lastSalePrice"),
            "net_change":  data.get("netChange"),
            "percent":     data.get("percentageChange"),
            "volume":      data.get("volume"),
            "session":     data.get("marketType") or "pre",
            "raw":         data,
        }
    except Exception:
        return None


# ─── Public API ───────────────────────────────────────────────────────────────

def fetch_pre_market_bars(symbol: str, *, lookback_minutes: int = 60) -> list[dict]:
    """Fetch pre-market 1-minute bars.

    PRIMARY  : Yahoo `v8/finance/chart` with includePrePost=true.
    FALLBACK : (none for bars – Nasdaq endpoint returns a summary only).

    Returns up to the last `lookback_minutes` bars from the current
    pre-market session, in chronological order. Fail-soft returns [].

    `lookback_minutes` is a soft cap (Yahoo returns ~1m granularity for
    1d range; we just slice the tail).
    """
    sym = _safe_symbol(symbol)
    if not sym:
        return []

    cache_key = (sym, "yahoo_pm_bars")
    cached = _cache_get(cache_key)
    if cached is not None:
        # Cached payload is already the full list of pre-market bars.
        # Slice for caller-requested lookback.
        return list(cached)[-max(1, int(lookback_minutes)):]

    bars = _fetch_yahoo_bars(sym)
    # Cache even empty result to avoid hammering on transient failure.
    _cache_set(cache_key, bars)
    if not bars:
        return []
    return bars[-max(1, int(lookback_minutes)):]


def fetch_pre_market_summary(symbol: str) -> dict | None:
    """Fetch a Nasdaq pre-market summary (single snapshot, no bars).

    Used as a fallback signal when Yahoo bars are unavailable. Returns
    None on any failure or empty symbol.
    """
    sym = _safe_symbol(symbol)
    if not sym:
        return None
    cache_key = (sym, "nasdaq_pm_summary")
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached if cached else None

    summary = _fetch_nasdaq_summary(sym)
    # Cache None as sentinel too; expires in 300s.
    _cache_set(cache_key, summary if summary is not None else {})
    return summary


def get_pre_market_context(symbol: str) -> dict:
    """Combined context dict consumed by callers building analyze_pre_open input.

    Returns shape:
      {
        "symbol":              str,
        "pre_market_bars":     list[bar],
        "prev_session_close":  float | None,
        "prev_session_high":   float | None,
        "prev_session_low":    float | None,
        "source":              "yahoo" | "nasdaq" | "unavailable",
        "fetched_at_iso":      str,
        "warnings":            list[str],
      }

    Previous-session OHLC comes from shared.market_data.get_daily_bars
    (Alpaca IEX, already free). If that fails, the fields are None.

    Fail-soft for empty or invalid symbol: returns context with empty bars,
    None prev-session fields, source=unavailable.
    """
    warnings: list[str] = []
    sym = _safe_symbol(symbol)
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    if not sym:
        warnings.append("empty_symbol")
        return {
            "symbol":             "",
            "pre_market_bars":    [],
            "prev_session_close": None,
            "prev_session_high":  None,
            "prev_session_low":   None,
            "source":             "unavailable",
            "fetched_at_iso":     fetched_at,
            "warnings":           warnings,
        }

    # Pre-market bars – Yahoo first.
    bars = fetch_pre_market_bars(symbol)
    source: str
    if bars:
        source = "yahoo"
    else:
        warnings.append("yahoo_no_bars")
        summary = fetch_pre_market_summary(symbol)
        if summary:
            source = "nasdaq"
        else:
            warnings.append("nasdaq_no_summary")
            source = "unavailable"

    # Previous session OHLC from Alpaca IEX daily bars (free).
    prev_close = prev_high = prev_low = None
    try:
        # Local import to avoid forcing market_data import side effects on
        # callers that don't need it (e.g. unit tests that monkeypatch).
        SHARED_DIR = os.path.dirname(os.path.abspath(__file__))
        if SHARED_DIR not in sys.path:
            sys.path.insert(0, SHARED_DIR)
        from market_data import get_daily_bars  # type: ignore
        daily = get_daily_bars(symbol, days=5)
        if daily and daily.get("close"):
            prev_close = float(daily["close"][-1])
            prev_high  = float(daily["high"][-1])
            prev_low   = float(daily["low"][-1])
    except Exception:
        # Fail-soft: leave prev_session_* as None
        warnings.append("daily_bars_fail")

    return {
        "symbol":             symbol if isinstance(symbol, str) else "",
        "pre_market_bars":    bars,
        "prev_session_close": prev_close,
        "prev_session_high":  prev_high,
        "prev_session_low":   prev_low,
        "source":             source,
        "fetched_at_iso":     fetched_at,
        "warnings":           warnings,
    }


__all__ = [
    "fetch_pre_market_bars",
    "fetch_pre_market_summary",
    "get_pre_market_context",
    "USER_AGENT",
    "CACHE_TTL_S",
    "HTTP_TIMEOUT_S",
]
