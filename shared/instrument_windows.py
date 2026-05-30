"""
shared/instrument_windows.py — per-instrument trading window gate.

Single point of truth: `can_trade_now(symbol, asset_class) -> (bool, str)`.
Wraps `place_order` calls across all monitors. Returns (allowed, reason)
so callers can log/route blocked orders to [DEFERRED] email instead of
[ERROR].

Decision precedence:
  1. instrument_overrides[symbol].enabled is False  → BLOCK (paused symbol)
  2. paused_until > today                           → BLOCK (auto-pause not yet expired)
  3. asset_class window says market closed          → BLOCK (market_closed)
  4. respect_us_holidays + today is US holiday      → BLOCK (holiday)
  5. else                                            → ALLOW

Asset-class window resolution:
  - "us_equity" / "us_option" → defers to shared.market_hours.is_us_market_open
    for canonical regular-hours + holidays (config days/times are documentation;
    the canonical computation lives in market_hours.py for one source of truth).
  - "crypto" → always allowed (24/7).
  - Anything else → BLOCK with "unknown asset_class" (fail-safe).

This module is imported by:
  - shared/alpaca_orders.py — guards every place_order entry point
  - shared/allocator.py — replaces inline market_hours check in _exec_*
  - exit-monitor / options-exit-monitor — guards SELL closes
  - Optionally: any monitor that wants to pre-flight before sending alert
"""

from __future__ import annotations  # v3.11.3: PEP 604 (X | None) parseable on Py 3.9 (local) + 3.11 (CI).

import json
import os
from datetime import datetime, date, timezone
from functools import lru_cache

try:
    from market_hours import is_us_market_open
except ImportError:
    from shared.market_hours import is_us_market_open


_REPO_ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_CONFIG_PATH = os.path.join(_REPO_ROOT, "config", "instrument_windows.json")


@lru_cache(maxsize=1)
def _load_config() -> dict:
    """Load + cache config. Cache cleared via _reset_cache() for tests."""
    try:
        with open(_CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"  instrument_windows: config unavailable ({e}) — fail-open")
        return {}


def _reset_cache():
    """For tests + workflow that mutates config mid-run."""
    _load_config.cache_clear()


# ─── Asset-class inference ────────────────────────────────────────────

def _infer_asset_class(symbol: str) -> str:
    """
    Best-effort asset class detection from symbol shape:
      "BTC/USD"            → crypto (any "/USD" pair)
      "AAPL260520P00270000" → us_option (OCC-style: ticker + 6 digit date + side + 8 digit strike)
      "AAPL" / "SPY"       → us_equity
    """
    if "/" in symbol:
        return "crypto"
    # OCC option symbol: ticker (1-6 chars) + YYMMDD (6 digits) + P/C + strike (8 digits)
    if len(symbol) >= 15 and symbol[-9] in ("P", "C") and symbol[-8:].isdigit():
        return "us_option"
    return "us_equity"


# ─── Per-symbol overrides ─────────────────────────────────────────────

def get_instrument_override(symbol: str) -> dict:
    """Returns override dict or {} if no override."""
    cfg = _load_config()
    overrides = (cfg.get("instrument_overrides") or {})
    return overrides.get(symbol) or {}


def _override_blocks(symbol: str, now: datetime) -> tuple[bool, str]:
    """
    Returns (blocked, reason). blocked=True means override says no.
    Reason is empty string when not blocked.
    """
    ov = get_instrument_override(symbol)
    if not ov:
        return False, ""
    if ov.get("enabled", True) is False:
        # Manually disabled. paused_until may still allow auto-resume.
        paused_until = ov.get("paused_until")
        if not paused_until:
            return True, f"{symbol} paused (manual): {ov.get('rationale', 'no rationale')[:80]}"
        try:
            until = date.fromisoformat(paused_until)
            if now.date() < until:
                return True, f"{symbol} paused until {paused_until}"
            # Past paused_until — auto-resume; treat as enabled
            return False, ""
        except ValueError:
            # Bad date → conservative block
            return True, f"{symbol} paused (invalid paused_until={paused_until!r})"
    return False, ""


# ─── Window resolution per asset class ────────────────────────────────

def _is_crypto_window_open(now: datetime) -> tuple[bool, str]:
    return True, "crypto 24/7"


def _is_us_window_open(now: datetime, asset_class: str) -> tuple[bool, str]:
    """Defer to canonical market_hours for US stocks + options."""
    open_, reason = is_us_market_open(now)
    if open_:
        return True, f"{asset_class} market open"
    return False, f"{asset_class} {reason}"   # e.g. "us_equity pre_market"


def _resolve_window(asset_class: str, now: datetime) -> tuple[bool, str]:
    if asset_class == "crypto":
        return _is_crypto_window_open(now)
    if asset_class in ("us_equity", "us_option"):
        return _is_us_window_open(now, asset_class)
    return False, f"unknown asset_class '{asset_class}'"


# ─── Public API ────────────────────────────────────────────────────────

def can_trade_now(symbol: str,
                   asset_class: str | None = None,
                   now: datetime | None = None) -> tuple[bool, str]:
    """
    Returns (allowed, reason).

    asset_class optional — inferred from symbol shape when None.
    now optional — current UTC time when None (for tests pass tz-aware datetime).

    Use in monitor code like:
      ok, reason = can_trade_now("MSTR", "us_equity")
      if not ok:
          notify_signal(signal, alert_sent=False, reason=reason)   # [DEFERRED]
          return
      place_stock_bracket(...)
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if asset_class is None:
        asset_class = _infer_asset_class(symbol)

    # 1. Per-symbol override (always wins)
    blocked, reason = _override_blocks(symbol, now)
    if blocked:
        return False, reason

    # 2. Asset-class window
    open_, reason = _resolve_window(asset_class, now)
    if not open_:
        return False, reason

    return True, "ok"


def is_extended_hours_enabled(symbol: str) -> bool:
    """
    True if symbol is on the extended_hours_opt_in list. Caller may pass
    extended_hours=true to Alpaca orders. Empty by default.
    """
    cfg = _load_config()
    syms = ((cfg.get("extended_hours_opt_in") or {}).get("symbols") or [])
    return symbol in syms


def list_paused_instruments() -> list[str]:
    """For banner-log / status reports. Symbols currently blocked by override."""
    cfg = _load_config()
    overrides = (cfg.get("instrument_overrides") or {})
    paused = []
    for sym, ov in overrides.items():
        if sym.startswith("_"):
            continue
        if not ov:
            continue
        if ov.get("enabled", True) is False:
            paused.append(sym)
    return paused


def asset_class_window(asset_class: str) -> dict:
    """Returns the config block for an asset class (for diagnostics)."""
    cfg = _load_config()
    return (cfg.get("default_windows") or {}).get(asset_class) or {}
