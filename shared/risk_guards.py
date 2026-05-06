"""
Shared risk guards used by all entry monitors (price, defense, crypto, geo).

vix_guard() should be called at the start of every monitor run BEFORE any
alert is dispatched. It fetches the current VIX level and returns:

  ("HALT",    0.0)  when VIX > 45  -> caller must skip the run entirely
  ("CAUTION", 0.5)  when VIX > 35  -> caller multiplies position sizes by 0.5
  ("OK",      1.0)  otherwise

VIX fetch fails open: if Finnhub is unreachable or FINNHUB_API_KEY is unset,
the guard returns OK so a Finnhub outage cannot silently kill all trading.
"""

import os
import requests

VIX_HALT_THRESHOLD    = 45.0
VIX_CAUTION_THRESHOLD = 35.0


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
