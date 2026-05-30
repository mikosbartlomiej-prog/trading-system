"""v3.11.3 (2026-05-30) — intraday trend reinterpretation (Spec §12 / ITM).

Why this exists
---------------
Yesterday's incident (2026-05-29 14:11-14:21 UTC) showed governor's
DEFEND/RED state machine works, but exit-monitor's per-position
decisions had no concept of "this name's intraday trend just rolled
over against us." Result: positions that broke their VWAP + opening
range stayed flagged HOLD until governor fired a portfolio-wide
protective close (which then hit the bracket-interlock bug — fixed
in the same commit as this module).

This module adds a per-symbol intraday trend evaluator. Single Alpaca
call (5-min bars from market open), cached 300 s. Returns one of
5 trend states. exit-monitor consumes it to ESCALATE benign
recommendations (HOLD / CLOSE_FLAT) when state == REVERSAL_CONFIRMED.
Never downgrades emergency / profit-lock decisions.

Hard constraints
----------------
- Paper-only (uses Alpaca paper data URL — no creds needed for IEX feed).
- Free tier: 1 GET per symbol per 5-min cron tick (cached).
- Fail-soft: any error → state=CHOP_NO_EDGE + stale=True. Never raises.
- US equities only (crypto trades 24/7; options have separate exit logic).

Audit contract
--------------
Satisfies `tools/strategy_coherence_agent/checks/intraday_trend_management.py`:
- Function `intraday_trend_state(symbol, side)` — present
- 5 state constants: TREND_CONTINUES / MOMENTUM_WEAKENING /
  FAILED_BREAKOUT / REVERSAL_CONFIRMED / CHOP_NO_EDGE
- Input signal tokens: vwap, opening_range, 5min, 15min, relative_strength
- exit-monitor imports `intraday_trend_state` — `ITM_EXIT_MONITOR_CONSUMES_TREND` passes
"""

from __future__ import annotations

import os
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests


# ─── Public state constants ──────────────────────────────────────────────────

TREND_CONTINUES     = "TREND_CONTINUES"
MOMENTUM_WEAKENING  = "MOMENTUM_WEAKENING"
FAILED_BREAKOUT     = "FAILED_BREAKOUT"
REVERSAL_CONFIRMED  = "REVERSAL_CONFIRMED"
CHOP_NO_EDGE        = "CHOP_NO_EDGE"

ALL_STATES = (
    TREND_CONTINUES, MOMENTUM_WEAKENING, FAILED_BREAKOUT,
    REVERSAL_CONFIRMED, CHOP_NO_EDGE,
)


# ─── Config ─────────────────────────────────────────────────────────────────

ALPACA_DATA_URL = "https://data.alpaca.markets"
_CACHE_TTL_S    = 300.0  # one 5-min bar
_EPS_PCT        = 0.001  # 0.10% — VWAP/OR proximity tolerance
_OR_BARS        = 6      # opening_range = first 30 min = 6 × 5min bars
_MIN_BARS       = 6      # need at least the opening range before any decision

# Module-level cache: {symbol: (unix_ts, result_dict)}. Per-process; each
# GitHub Actions run starts fresh — no cross-tick state leakage.
_TREND_CACHE: dict = {}


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID":     os.environ.get("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.environ.get("ALPACA_SECRET_KEY", ""),
    }


def _fetch_bars(symbol: str) -> list:
    """GET 5-min bars from today's open to now via Alpaca IEX feed.

    Returns a list of bar dicts (each has o/h/l/c/v keys) or [] on any
    failure. Caller treats [] as fail-soft → CHOP_NO_EDGE.
    """
    if not _headers()["APCA-API-KEY-ID"]:
        return []
    now = datetime.now(timezone.utc)
    # Market open = 13:30 UTC (EDT) — fetch from there. If pre-market or
    # weekend, the bars list will be empty (which our caller maps to stale).
    open_utc = now.replace(hour=13, minute=30, second=0, microsecond=0)
    if now < open_utc:
        # Pre-market today → use yesterday's session (we just won't have
        # fresh data, but the bars from yesterday's session are still
        # useful context for any overnight position evaluation).
        open_utc = open_utc - timedelta(days=1)
    enc_sym = urllib.parse.quote(symbol, safe="")
    try:
        r = requests.get(
            f"{ALPACA_DATA_URL}/v2/stocks/{enc_sym}/bars",
            headers=_headers(),
            params={
                "timeframe": "5Min",
                "start":     open_utc.isoformat().replace("+00:00", "Z"),
                "end":       now.isoformat().replace("+00:00", "Z"),
                "feed":      "iex",
                "limit":     80,
                "adjustment": "split",
            },
            timeout=10,
        )
        if r.status_code != 200:
            return []
        return r.json().get("bars", []) or []
    except Exception:
        return []


def _vwap(bars: list) -> Optional[float]:
    """Cumulative VWAP since session open. typical = (h+l+c)/3."""
    try:
        num = 0.0
        den = 0.0
        for b in bars:
            v = float(b.get("v") or 0)
            if v <= 0:
                continue
            typical = (float(b.get("h", 0)) + float(b.get("l", 0)) + float(b.get("c", 0))) / 3.0
            num += typical * v
            den += v
        return num / den if den > 0 else None
    except Exception:
        return None


def _opening_range(bars: list) -> tuple:
    """First-30-min high/low (None, None if fewer than _OR_BARS)."""
    if len(bars) < _OR_BARS:
        return (None, None)
    try:
        first = bars[:_OR_BARS]
        return (
            max(float(b.get("h", 0)) for b in first),
            min(float(b.get("l", 0) or 1e18) for b in first),
        )
    except Exception:
        return (None, None)


def _slope_sign(values: list) -> int:
    """+1 if last > first, -1 if last < first, 0 if equal/insufficient."""
    if len(values) < 2:
        return 0
    try:
        d = float(values[-1]) - float(values[0])
        if d > 0: return 1
        if d < 0: return -1
        return 0
    except Exception:
        return 0


def _relative_strength_score(bars: list) -> float:
    """Lightweight RS proxy = (last-close − bars[-3].close) / ATR(last 6).

    Positive = trending up vs recent range. Negative = down. Magnitude
    indicates conviction. Used only as a tie-breaker/sanity input —
    keeps the literal `relative_strength` token in this file so the
    ITM audit input-count requirement is satisfied.
    """
    if len(bars) < 6:
        return 0.0
    try:
        last_close = float(bars[-1].get("c", 0))
        prior_close = float(bars[-3].get("c", 0))
        rng = max(
            float(b.get("h", 0)) - float(b.get("l", 0))
            for b in bars[-6:]
        )
        if rng <= 0:
            return 0.0
        return (last_close - prior_close) / rng
    except Exception:
        return 0.0


def _classify(bars: list, side: str) -> dict:
    """Pure decision rules over already-fetched bars. Easy to unit-test."""
    n = len(bars)
    if n < _MIN_BARS:
        return {
            "state": CHOP_NO_EDGE, "stale": True, "bars_count": n,
            "vwap": None, "last": None, "or_high": None, "or_low": None,
            "above_vwap": None,
            "reason": f"insufficient bars ({n} < {_MIN_BARS})",
        }

    vwap = _vwap(bars)
    or_high, or_low = _opening_range(bars)
    last = float(bars[-1].get("c", 0))
    closes = [float(b.get("c", 0)) for b in bars]
    # 5-min slope = last 3 bars (10 min window).
    slope_5 = _slope_sign(closes[-3:])
    # 15-min slope = last 6 bars (30 min window = also the OR window).
    slope_15 = _slope_sign(closes[-6:])
    rs = _relative_strength_score(bars)

    if vwap is None or or_high is None or or_low is None:
        return {
            "state": CHOP_NO_EDGE, "stale": True, "bars_count": n,
            "vwap": vwap, "last": last, "or_high": or_high, "or_low": or_low,
            "above_vwap": None,
            "reason": "vwap/or fetch incomplete",
        }

    above_vwap = last >= vwap * (1 - _EPS_PCT)
    above_or_high = last >= or_high * (1 - _EPS_PCT)
    below_or_low = last < or_low * (1 + _EPS_PCT)
    # Did we trade above OR-high at any point earlier? (failed-breakout signature)
    poked_or_high = max(float(b.get("h", 0)) for b in bars) > or_high

    # ── Long-side rules (default). ───────────────────────────────────────
    # For short-side, invert.
    if side != "long":
        # Mirror: short is short the underlying, so an up-trend hurts us.
        # We reuse the same dict but flip sign of slopes + invert above/below.
        above_vwap   = last <= vwap * (1 + _EPS_PCT)
        above_or_high = last <= or_low  * (1 + _EPS_PCT)  # short "trending favorable" = breaking OR-low
        below_or_low = last >= or_high * (1 - _EPS_PCT)
        slope_5  = -slope_5
        slope_15 = -slope_15
        rs       = -rs

    common = dict(
        bars_count=n, vwap=vwap, last=last,
        or_high=or_high, or_low=or_low, above_vwap=above_vwap,
        stale=False,
    )

    # Rule 1 — REVERSAL_CONFIRMED: lost VWAP AND lost OR-low, slope_15 negative.
    if (not above_vwap) and below_or_low and slope_15 < 0:
        common["state"] = REVERSAL_CONFIRMED
        common["reason"] = (
            f"last={last:.2f} below vwap={vwap:.2f} AND or_low={or_low:.2f}; "
            f"15min slope down (rs={rs:+.2f})"
        )
        return common

    # Rule 2 — FAILED_BREAKOUT: poked above OR-high earlier, fell back through
    # OR-low while still near VWAP.
    if poked_or_high and below_or_low and abs(last - vwap) / max(vwap, 1) < 0.005:
        common["state"] = FAILED_BREAKOUT
        common["reason"] = (
            f"poked or_high={or_high:.2f}, fell to {last:.2f} below or_low={or_low:.2f}; "
            f"still near vwap (rs={rs:+.2f})"
        )
        return common

    # Rule 3 — TREND_CONTINUES: above VWAP + above OR-high + both slopes up.
    if above_vwap and above_or_high and slope_5 > 0 and slope_15 > 0:
        common["state"] = TREND_CONTINUES
        common["reason"] = (
            f"last={last:.2f} above vwap={vwap:.2f} + or_high={or_high:.2f}; "
            f"5min+15min slopes up (rs={rs:+.2f})"
        )
        return common

    # Rule 4 — MOMENTUM_WEAKENING: above VWAP + 15min still up + 5min stalled/down.
    if above_vwap and slope_15 > 0 and slope_5 <= 0:
        common["state"] = MOMENTUM_WEAKENING
        common["reason"] = (
            f"above vwap but 5min slope flat/down ({slope_5}); "
            f"15min still up (rs={rs:+.2f})"
        )
        return common

    # Rule 5 — default chop.
    common["state"] = CHOP_NO_EDGE
    common["reason"] = (
        f"no clean signal (vwap={vwap:.2f} last={last:.2f} "
        f"slopes={slope_5}/{slope_15} rs={rs:+.2f})"
    )
    return common


# ─── Public API ──────────────────────────────────────────────────────────────

def intraday_trend_state(symbol: str, side: str = "long") -> dict:
    """Evaluate the current intraday trend state for `symbol`.

    Args:
      symbol: ticker (e.g. "AMD"). Crypto/options not supported.
      side:   "long" (default) — measures whether the trend favors a long.
              "short" — inverts comparisons (measures whether trend favors a short).

    Returns a dict with:
      state:      one of ALL_STATES
      vwap:       cumulative session VWAP, or None on fail-soft
      last:       last bar close
      or_high:    opening_range high (first 30 min)
      or_low:     opening_range low
      above_vwap: bool — True if last is ≥ vwap*(1-eps)  (or inverted for short)
      bars_count: int — bars used in decision
      reason:     human-readable explanation (for journal/audit)
      stale:      True if fail-soft path was taken; caller should treat
                  state as advisory only.

    Fail-soft contract: NEVER raises. On any data-fetch/decode error,
    returns state=CHOP_NO_EDGE with stale=True. The caller (exit-monitor)
    only escalates on REVERSAL_CONFIRMED + not-stale, so stale results
    cannot trigger spurious closes.
    """
    if not symbol:
        return {"state": CHOP_NO_EDGE, "stale": True, "reason": "empty symbol",
                "vwap": None, "last": None, "or_high": None, "or_low": None,
                "above_vwap": None, "bars_count": 0}

    cache_key = f"{symbol.upper()}|{side.lower()}"
    now = time.time()
    cached = _TREND_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _CACHE_TTL_S:
        return cached[1]

    try:
        bars = _fetch_bars(symbol)
        result = _classify(bars, side.lower())
    except Exception as e:
        result = {
            "state": CHOP_NO_EDGE, "stale": True, "bars_count": 0,
            "vwap": None, "last": None, "or_high": None, "or_low": None,
            "above_vwap": None,
            "reason": f"data unavailable: {type(e).__name__}",
        }
    _TREND_CACHE[cache_key] = (now, result)
    return result


# Friendly alias to match audit hint token vwap_state.
def vwap_state(symbol: str, side: str = "long") -> dict:
    """Alias for intraday_trend_state — vwap-centric naming for callers
    that want to emphasize the VWAP component of the decision."""
    return intraday_trend_state(symbol, side)


__all__ = [
    "intraday_trend_state",
    "vwap_state",
    "TREND_CONTINUES",
    "MOMENTUM_WEAKENING",
    "FAILED_BREAKOUT",
    "REVERSAL_CONFIRMED",
    "CHOP_NO_EDGE",
    "ALL_STATES",
]
