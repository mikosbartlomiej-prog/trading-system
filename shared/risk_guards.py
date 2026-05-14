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

from __future__ import annotations

import os
import urllib.parse
import requests

# v2.0 risk-on: HALT only at extreme stress; CAUTION removed (no auto de-sizing)
# (was: HALT 45, CAUTION 35)
VIX_HALT_THRESHOLD    = 60.0
VIX_CAUTION_THRESHOLD = 999.0   # effectively disabled — the CAUTION branch never fires

# v3.0 (2026-05-12) aggressive profile — values come from
# config/aggressive_profile.json via shared/profile.py. Constants here
# are DEFAULTS used when profile unavailable / corrupted. Read fresh
# from profile each call so config changes take effect without restart.
DAILY_DRAWDOWN_HALT_PCT  = -3.0    # v3.0 aggressive (was -12% in v2.0)
WEEKLY_DRAWDOWN_HALT_PCT = -7.0    # NEW v3.0
MAX_DRAWDOWN_DEFENSIVE_PCT = -12.0  # NEW v3.0 — trigger defensive mode
MAX_DRAWDOWN_FULL_STOP_PCT = -20.0  # NEW v3.0 — emergency-close all via emergency_engine
POSITION_PCT_CAP         = 40.0    # block new entries if combined pos% > 40% equity

ALPACA_BASE_URL = "https://paper-api.alpaca.markets"


def _vix_from_finnhub() -> float | None:
    """Fetch VIX from Finnhub /quote. Free tier currently returns 0 for ^VIX
    (the endpoint moved to a paid plan mid-2024) — kept here as preferred
    source in case the free tier is restored. Returns None on failure / 0."""
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
        print(f"  VIX/Finnhub error: {e}")
        return None


def _vix_from_yahoo() -> float | None:
    """Fetch VIX from Yahoo Finance public chart endpoint. No API key
    required. Returns None on failure. Brittle (Yahoo can change response
    format without notice) — used as fallback when Finnhub is empty."""
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX",
            params={"interval": "1d", "range": "1d"},
            headers={"User-Agent": "trading-system/1.0 (mikosbartlomiej-prog)"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        result = (data.get("chart") or {}).get("result") or []
        if not result:
            return None
        meta = result[0].get("meta") or {}
        price = meta.get("regularMarketPrice")
        if isinstance(price, (int, float)) and price > 0:
            return float(price)
        return None
    except Exception as e:
        print(f"  VIX/Yahoo error: {e}")
        return None


def get_vix() -> float | None:
    """
    Fetch current VIX with provider fallback chain:
      1. Finnhub `/quote?symbol=^VIX` (preferred — paid tier returns proper
         data; free tier currently returns 0)
      2. Yahoo Finance public chart endpoint (free, no key, brittle)

    Returns the first non-None positive number, or None if all sources
    fail. Caller (`vix_guard`) treats None as fail-open (normal sizing).
    """
    for fetcher_name, fetcher in (("finnhub", _vix_from_finnhub),
                                   ("yahoo",   _vix_from_yahoo)):
        v = fetcher()
        if v is not None:
            print(f"  VIX from {fetcher_name}: {v:.2f}")
            return v
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


def get_account_status() -> dict | None:
    """
    Fetch account snapshot once per monitor run.

    Returns a dict with equity / last_equity / daily_pl_pct / buying_power,
    or None on missing creds / API failure (fail-open).
    """
    api_key    = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        return None
    try:
        r = requests.get(
            f"{ALPACA_BASE_URL}/v2/account",
            headers={
                "APCA-API-KEY-ID":     api_key,
                "APCA-API-SECRET-KEY": secret_key,
            },
            timeout=10,
        )
        r.raise_for_status()
        d = r.json()
        equity      = float(d.get("equity", 0))
        last_equity = float(d.get("last_equity", equity or 1))
        daily_pl_pct = ((equity - last_equity) / last_equity * 100) if last_equity > 0 else 0.0
        return {
            "equity":       equity,
            "last_equity":  last_equity,
            "daily_pl_pct": daily_pl_pct,
            "buying_power": float(d.get("buying_power", 0)),
        }
    except Exception as e:
        print(f"  account status error: {e}")
        return None


def _profile_threshold_pct(key: str, default_pct: float) -> float:
    """
    Read a drawdown threshold from aggressive_profile.json::risk_limits.
    Profile stores values as fractions (0.03 = 3%); this function returns
    SIGNED PERCENT (so 0.03 → -3.0 for daily loss threshold).
    """
    try:
        from profile import profile_value
    except ImportError:
        try:
            from shared.profile import profile_value
        except ImportError:
            return default_pct
    val = profile_value(f"risk_limits.{key}")
    if val is None:
        return default_pct
    try:
        # Profile stores fractional (0.03); convert to negative percent
        return -float(val) * 100
    except (TypeError, ValueError):
        return default_pct


def daily_drawdown_guard(account: dict | None = None) -> tuple[str, str]:
    """
    Account-level circuit breaker. Threshold from aggressive_profile.json
    ::risk_limits.max_daily_loss_pct_equity (default -3% in v3.0 aggressive;
    was -12% in v2.0).

    Returns:
      ("HALT", reason)  when daily P&L <= max_daily_loss threshold
      ("OK", reason)    otherwise (including fail-open on API failure)
    """
    acct = account if account is not None else get_account_status()
    if not acct:
        print("  Drawdown guard: account data unavailable -> proceeding (fail-open)")
        return "OK", "fail-open"
    pl = acct["daily_pl_pct"]
    threshold = _profile_threshold_pct("max_daily_loss_pct_equity",
                                          DAILY_DRAWDOWN_HALT_PCT)
    if pl <= threshold:
        msg = f"daily P&L {pl:+.2f}% <= {threshold:+.1f}% -> HALT new entries"
        print(f"  Drawdown guard: {msg}")
        return "HALT", msg
    print(f"  Drawdown guard: daily P&L {pl:+.2f}% (threshold {threshold:+.1f}%) -> OK")
    return "OK", f"daily P&L {pl:+.2f}%"


def weekly_drawdown_guard(account: dict | None = None,
                            weekly_start_equity: float | None = None
                            ) -> tuple[str, str]:
    """
    Weekly drawdown circuit breaker. v3.0 aggressive profile threshold
    is -7%. Triggers `WARN` (not HALT) — operator/LLM decide whether to
    pause; some strategies (overbought-short in falling tape) may still
    want to fire.

    `weekly_start_equity` should be the Monday open equity, persisted
    by the workflow. If None, falls back to last_equity from /v2/account
    (only gives intraday, NOT week — but better than nothing as a
    safety net).

    Returns:
      ("HALT", reason)  when weekly P&L <= max_weekly_loss threshold
      ("WARN", reason)  when within 1pp of threshold
      ("OK", reason)    otherwise
    """
    acct = account if account is not None else get_account_status()
    if not acct:
        return "OK", "fail-open"
    if weekly_start_equity is None:
        # Approximation: use last_equity (yesterday's close)
        weekly_start_equity = acct.get("last_equity")
    if not weekly_start_equity or weekly_start_equity <= 0:
        return "OK", "fail-open (no baseline)"

    equity_now = acct["equity"]
    week_pl_pct = (equity_now - weekly_start_equity) / weekly_start_equity * 100
    threshold = _profile_threshold_pct("max_weekly_loss_pct_equity", WEEKLY_DRAWDOWN_HALT_PCT)
    if week_pl_pct <= threshold:
        msg = f"weekly P&L {week_pl_pct:+.2f}% <= {threshold:+.1f}% -> HALT"
        print(f"  Weekly guard: {msg}")
        return "HALT", msg
    if week_pl_pct <= threshold + 1.0:
        msg = f"weekly P&L {week_pl_pct:+.2f}% within 1pp of {threshold:+.1f}% -> WARN"
        print(f"  Weekly guard: {msg}")
        return "WARN", msg
    return "OK", f"weekly P&L {week_pl_pct:+.2f}%"


def max_drawdown_guard(account: dict | None = None,
                        peak_equity: float | None = None
                        ) -> tuple[str, str]:
    """
    Trailing max drawdown from peak. Two thresholds:
      -12% (defensive mode) → returns "DEFENSIVE"
      -20% (full stop)      → returns "FULL_STOP"

    `peak_equity` should come from learning-loop/state.json::peak_equity
    (workflow updates it each daily-learning run). Falls back to
    last_equity (very approximate — last day's close).

    Returns ("OK", reason) | ("DEFENSIVE", reason) | ("FULL_STOP", reason).
    """
    acct = account if account is not None else get_account_status()
    if not acct:
        return "OK", "fail-open"
    if peak_equity is None:
        peak_equity = acct.get("last_equity") or acct.get("equity")
    if not peak_equity or peak_equity <= 0:
        return "OK", "fail-open (no peak baseline)"

    equity_now = acct["equity"]
    dd_pct = (equity_now - peak_equity) / peak_equity * 100
    full_stop = _profile_threshold_pct("max_drawdown_full_stop_pct", MAX_DRAWDOWN_FULL_STOP_PCT)
    defensive = _profile_threshold_pct("max_drawdown_defensive_mode_pct", MAX_DRAWDOWN_DEFENSIVE_PCT)
    if dd_pct <= full_stop:
        msg = f"drawdown {dd_pct:+.2f}% <= {full_stop:+.1f}% -> FULL_STOP (autonomous emergency-close triggered)"
        print(f"  Max-DD guard: {msg}")
        return "FULL_STOP", msg
    if dd_pct <= defensive:
        msg = f"drawdown {dd_pct:+.2f}% <= {defensive:+.1f}% -> DEFENSIVE mode"
        print(f"  Max-DD guard: {msg}")
        return "DEFENSIVE", msg
    return "OK", f"drawdown {dd_pct:+.2f}%"


def position_pct(symbol: str, equity: float | None = None) -> float:
    """
    Return % of equity currently held in `symbol`.

    Returns 0.0 when no position, no creds, or API failure (fail-open —
    a stale Alpaca outage cannot silently block entries).

    Pass `equity` from get_account_status() to avoid an extra round-trip.
    """
    api_key    = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        return 0.0
    if equity is None:
        acct = get_account_status()
        if not acct or acct["equity"] <= 0:
            return 0.0
        equity = acct["equity"]
    if equity <= 0:
        return 0.0
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
        if r.status_code == 404:
            return 0.0
        if r.status_code != 200:
            return 0.0
        market_value = abs(float(r.json().get("market_value", 0) or 0))
        return market_value / equity * 100.0
    except Exception:
        return 0.0


def concentration_ok(symbol: str, new_size_usd: float,
                      equity: float | None = None) -> tuple[bool, float]:
    """
    True iff (existing position % + new size %) <= POSITION_PCT_CAP.

    Returns (ok, combined_pct) so the caller can log the actual figure.
    """
    if equity is None:
        acct = get_account_status()
        if not acct or acct["equity"] <= 0:
            return True, 0.0   # fail-open
        equity = acct["equity"]
    if equity <= 0:
        return True, 0.0
    pos_pct = position_pct(symbol, equity=equity)
    new_pct = (new_size_usd / equity) * 100.0
    combined = pos_pct + new_pct
    return combined <= POSITION_PCT_CAP, combined


def get_open_positions() -> list[dict]:
    """
    Fetch ALL open positions in one call (cheaper than per-symbol queries).

    Returns list of normalized dicts:
      {
        "symbol":   "AAPL" | "AMZN260520P00270000" (OCC options),
        "asset_class": "us_equity" | "crypto" | "us_option",
        "side":     "long" | "short",
        "qty":      float,
        "avg_entry_price": float,
        "current_price":   float,
        "market_value":    float,
        "unrealized_pl":   float,
        "unrealized_plpc": float (already in fractional, e.g. -0.178 for -17.8%),
      }

    Fail-open: returns [] on missing creds or API error so callers can
    decide between "no positions" and "API down — assume no positions"
    via a fallback parameter.
    """
    api_key    = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        return []
    try:
        r = requests.get(
            f"{ALPACA_BASE_URL}/v2/positions",
            headers={
                "APCA-API-KEY-ID":     api_key,
                "APCA-API-SECRET-KEY": secret_key,
            },
            timeout=10,
        )
        if r.status_code != 200:
            print(f"  positions: HTTP {r.status_code} -> empty list")
            return []
        out = []
        for p in r.json():
            try:
                out.append({
                    "symbol":           p.get("symbol", ""),
                    "asset_class":      p.get("asset_class", "us_equity"),
                    "side":             p.get("side", "long"),
                    "qty":              float(p.get("qty", 0) or 0),
                    "avg_entry_price":  float(p.get("avg_entry_price", 0) or 0),
                    "current_price":    float(p.get("current_price", 0) or 0),
                    "market_value":     float(p.get("market_value", 0) or 0),
                    "unrealized_pl":    float(p.get("unrealized_pl", 0) or 0),
                    "unrealized_plpc":  float(p.get("unrealized_plpc", 0) or 0),
                })
            except (TypeError, ValueError):
                continue
        return out
    except Exception as e:
        print(f"  positions: error: {e}")
        return []


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
