"""
Shared risk guards used by all entry monitors (price, defense, crypto, geo).

vix_guard() should be called at the start of every monitor run BEFORE any
alert is dispatched. It fetches the current VIX level and returns:

  ("HALT", 0.0)  when VIX > 60  -> caller must skip the run entirely
  ("OK",   1.0)  otherwise

v2.0 risk-on (2026-05-06): CAUTION mode REMOVED. The system embraces
volatility now and only halts on catastrophic stress (VIX > 60).
Old behavior: HALT@45 / CAUTION@35 (50% sizing); see git history.

VIX fetch fails open: if Finnhub is unreachable or FINNHUB_API_KEY is unset,
the guard returns OK so a Finnhub outage cannot silently kill all trading.
"""

import os
import urllib.parse
import requests

# v2.0 risk-on: HALT only at extreme stress; CAUTION removed (no auto de-sizing)
# (was: HALT 45, CAUTION 35)
VIX_HALT_THRESHOLD    = 60.0
VIX_CAUTION_THRESHOLD = 999.0   # effectively disabled — the CAUTION branch never fires

ALPACA_BASE_URL = "https://paper-api.alpaca.markets"


def get_vix() -> float | None:
    """Fetch current VIX index level via Finnhub. Returns None on failure."""
    api_key = os.environ.get("FINNHUB_API_KEY", "")
    if not api_key:
        return None
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": "^VIX", "token": api_key},
            timeout=10,
        )
        r.raise_for_status()
        c = float(r.json().get("c", 0))
        return c if c > 0 else None
    except Exception as e:
        print(f"  VIX fetch error: {e}")
        return None


def vix_guard() -> tuple[str, float]:
    """
    Returns (status, size_multiplier).
      status: "HALT" | "CAUTION" | "OK"
      size_multiplier: 0.0 | 0.5 | 1.0
    """
    vix = get_vix()
    if vix is None:
        print("  VIX guard: unable to fetch VIX -> proceeding with normal sizing")
        return "OK", 1.0
    if vix > VIX_HALT_THRESHOLD:
        print(f"  VIX guard: VIX={vix:.1f} > {VIX_HALT_THRESHOLD} -> HALT (no alerts this run)")
        return "HALT", 0.0
    if vix > VIX_CAUTION_THRESHOLD:
        print(f"  VIX guard: VIX={vix:.1f} > {VIX_CAUTION_THRESHOLD} -> CAUTION (50% sizing)")
        return "CAUTION", 0.5
    print(f"  VIX guard: VIX={vix:.1f} -> OK (normal sizing)")
    return "OK", 1.0


def has_open_position(symbol: str) -> bool:
    """
    Check whether Alpaca already holds a position for `symbol`.

    Returns True only when Alpaca confirms a position exists.
    Fails OPEN: missing credentials, network errors or unexpected status
    codes return False so a single Alpaca outage cannot silently block
    every entry signal across all monitors.

    Crypto symbols ("BTC/USD") are URL-encoded so the slash survives the path.
    """
    api_key    = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        return False
    try:
        encoded = urllib.parse.quote(symbol, safe='')
        r = requests.get(
            f"{ALPACA_BASE_URL}/v2/positions/{encoded}",
            headers={
                "APCA-API-KEY-ID":     api_key,
                "APCA-API-SECRET-KEY": secret_key,
            },
            timeout=10,
        )
        if r.status_code == 200:
            return True
        if r.status_code == 404:
            return False
        print(f"  dup-guard: unexpected HTTP {r.status_code} for {symbol} -> fail open")
        return False
    except Exception as e:
        print(f"  dup-guard: error checking {symbol}: {e} -> fail open")
        return False
