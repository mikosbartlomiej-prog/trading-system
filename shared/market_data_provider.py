"""v3.27.0 (2026-06-09) — read-only market data provider for shadow evidence.

The v3.27 automated shadow-evidence pipeline must fetch live prices
for SPY/QQQ/GLD/AMD/CRWD/NOW/PANW/ORCL and BTC/ETH/SOL/LTC/AVAX
without coupling to any broker-execution module.

Design (per v3.27 discovery — see docs/SIGNAL_SHADOW_EVIDENCE_COLLECTION_RUNBOOK.md):
- Reuses ``shared/market_data.py::get_daily_bars`` for stocks (already
  read-only, IEX feed, paper API key, no broker side effects).
- Implements lightweight latest-quote helpers IN THIS MODULE using the
  same ``data.alpaca.markets`` endpoint that ``alpaca_orders.py`` uses,
  but WITHOUT importing ``alpaca_orders.py``. This decouples shadow
  callers from the broker module.
- Crypto bars + crypto quotes via ``v1beta3/crypto/us/...`` paths
  (read-only).
- All endpoints hit ``data.alpaca.markets`` — a strict read-only host.
  The broker host ``paper-api.alpaca.markets`` is NEVER touched by this
  module (asserted by ``NEVER_TOUCHES_BROKER_HOST``).

CONTRACT
--------
- READ-ONLY. Does NOT submit orders.
- Does NOT call any function in ``shared/alpaca_orders.py``.
- Does NOT call the broker host.
- Returns ``MarketSnapshot`` dataclass with explicit ``data_quality``
  enum. Missing / stale / errored data is returned as ``NO_MARKET_DATA``
  / ``STALE_MARKET_DATA`` / ``PROVIDER_ERROR`` — never fabricated.

INVARIANTS (test-asserted)
--------------------------
- NEVER_SUBMITS_ORDERS = True
- NEVER_TOUCHES_BROKER_HOST = True
- NEVER_IMPORTS_ALPACA_ORDERS = True
- NEVER_FABRICATES_PRICE = True
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

# ─── Data quality enum ──────────────────────────────────────────────────────

REAL_MARKET_DATA   = "REAL_MARKET_DATA"
NO_MARKET_DATA     = "NO_MARKET_DATA"
STALE_MARKET_DATA  = "STALE_MARKET_DATA"
PROVIDER_ERROR     = "PROVIDER_ERROR"

ALL_DATA_QUALITIES: frozenset[str] = frozenset({
    REAL_MARKET_DATA, NO_MARKET_DATA,
    STALE_MARKET_DATA, PROVIDER_ERROR,
})

# Invariants.
NEVER_SUBMITS_ORDERS        = True
NEVER_TOUCHES_BROKER_HOST   = True
NEVER_IMPORTS_ALPACA_ORDERS = True
NEVER_FABRICATES_PRICE      = True

# Read-only data API host.
ALPACA_DATA_URL = "https://data.alpaca.markets"
# Hard-pinned forbidden host (a test asserts we never reference it).
_FORBIDDEN_BROKER_HOST = "paper-api.alpaca.markets"

# Default monitored universes for v3.27 shadow opportunity generation.
DEFAULT_EQUITY_SYMBOLS = (
    "SPY", "QQQ", "GLD", "AMD", "CRWD", "NOW", "PANW", "ORCL",
)
DEFAULT_CRYPTO_SYMBOLS = (
    "BTC/USD", "ETH/USD", "SOL/USD", "LTC/USD", "AVAX/USD",
)

# Staleness budget (seconds) for a snapshot to count as REAL_MARKET_DATA.
DEFAULT_STALE_BUDGET_SECONDS = 1800   # 30 min


# ─── Snapshot dataclass ──────────────────────────────────────────────────────

@dataclass
class MarketSnapshot:
    symbol: str
    asset_class: str  # "us_equity" | "crypto"
    timestamp: float | None              # epoch seconds (None on ERROR/NO_DATA)
    price: float | None                  # mid or last
    bid: float | None = None
    ask: float | None = None
    volume: float | None = None
    source: str = "alpaca_data"
    data_quality: str = NO_MARKET_DATA
    stale_seconds: float | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "asset_class": self.asset_class,
            "timestamp": self.timestamp,
            "price": self.price,
            "bid": self.bid,
            "ask": self.ask,
            "volume": self.volume,
            "source": self.source,
            "data_quality": self.data_quality,
            "stale_seconds": self.stale_seconds,
            "error": self.error,
        }


# ─── Internal helpers ────────────────────────────────────────────────────────

def _headers() -> dict[str, str] | None:
    """Build read-only headers using paper API key.

    The key is the SAME paper key used elsewhere in the repo, but the
    base URL is the data host (``data.alpaca.markets``), not the broker
    host (``paper-api.alpaca.markets``). Even if the key were live, the
    data endpoint cannot place orders.
    """
    key = os.environ.get("ALPACA_API_KEY")
    sec = os.environ.get("ALPACA_SECRET_KEY")
    if not key or not sec:
        return None
    return {
        "APCA-API-KEY-ID":     key,
        "APCA-API-SECRET-KEY": sec,
    }


def _now() -> float:
    return time.time()


def _stale_seconds(ts_iso: str) -> float | None:
    """Best-effort: parse an ISO-8601 timestamp + return age in seconds."""
    try:
        from datetime import datetime, timezone
        if ts_iso.endswith("Z"):
            ts_iso = ts_iso[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return _now() - dt.timestamp()
    except Exception:
        return None


def _grade_quality(stale_seconds: float | None,
                   *, budget_seconds: float) -> str:
    if stale_seconds is None:
        return PROVIDER_ERROR
    if stale_seconds < 0:
        # Clock skew — treat as fresh.
        return REAL_MARKET_DATA
    if stale_seconds <= budget_seconds:
        return REAL_MARKET_DATA
    return STALE_MARKET_DATA


# ─── Public API ──────────────────────────────────────────────────────────────

def fetch_equity_quote(
    symbol: str,
    *,
    stale_budget_seconds: float = DEFAULT_STALE_BUDGET_SECONDS,
    timeout_seconds: float = 5.0,
) -> MarketSnapshot:
    """Read-only latest quote for a US equity ticker.

    Returns a ``MarketSnapshot``. Fails soft: any error is recorded
    on the snapshot rather than raised. Never fabricates price.
    """
    headers = _headers()
    if headers is None:
        return MarketSnapshot(
            symbol=symbol, asset_class="us_equity",
            timestamp=None, price=None,
            data_quality=NO_MARKET_DATA,
            error="ALPACA_API_KEY / ALPACA_SECRET_KEY not set",
        )
    try:
        import requests
        url = (f"{ALPACA_DATA_URL}/v2/stocks/{symbol}/quotes/latest"
                f"?feed=iex")
        r = requests.get(url, headers=headers, timeout=timeout_seconds)
        if r.status_code != 200:
            return MarketSnapshot(
                symbol=symbol, asset_class="us_equity",
                timestamp=None, price=None,
                data_quality=PROVIDER_ERROR,
                error=f"HTTP {r.status_code}",
            )
        body = r.json() or {}
        q = body.get("quote") or {}
        bid = q.get("bp")
        ask = q.get("ap")
        ts_iso = q.get("t") or ""
        if bid is None and ask is None:
            return MarketSnapshot(
                symbol=symbol, asset_class="us_equity",
                timestamp=None, price=None,
                data_quality=NO_MARKET_DATA,
                error="missing bid/ask in quote payload",
            )
        try:
            bid_f = float(bid) if bid is not None else None
            ask_f = float(ask) if ask is not None else None
        except (TypeError, ValueError):
            return MarketSnapshot(
                symbol=symbol, asset_class="us_equity",
                timestamp=None, price=None,
                data_quality=PROVIDER_ERROR,
                error="non-numeric bid/ask",
            )
        mid: float | None = None
        if bid_f and ask_f and bid_f > 0 and ask_f > 0:
            mid = round((bid_f + ask_f) / 2.0, 4)
        else:
            mid = bid_f or ask_f
        stale = _stale_seconds(ts_iso)
        quality = _grade_quality(stale, budget_seconds=stale_budget_seconds)
        return MarketSnapshot(
            symbol=symbol, asset_class="us_equity",
            timestamp=_now() - (stale or 0.0),
            price=mid, bid=bid_f, ask=ask_f,
            data_quality=quality,
            stale_seconds=stale,
        )
    except Exception as e:
        return MarketSnapshot(
            symbol=symbol, asset_class="us_equity",
            timestamp=None, price=None,
            data_quality=PROVIDER_ERROR,
            error=f"{type(e).__name__}: {e}",
        )


def fetch_crypto_quote(
    symbol: str,
    *,
    stale_budget_seconds: float = DEFAULT_STALE_BUDGET_SECONDS,
    timeout_seconds: float = 5.0,
) -> MarketSnapshot:
    """Read-only latest crypto quote.

    ``symbol`` may be ``BTC/USD`` (Alpaca format) or ``BTCUSD``.
    """
    if "/" not in symbol:
        # Accept BTCUSD-style; convert to BTC/USD.
        if symbol.upper().endswith("USD"):
            symbol = f"{symbol[:-3].upper()}/USD"
    headers = _headers()
    try:
        import requests
        url = (f"{ALPACA_DATA_URL}/v1beta3/crypto/us/latest/quotes"
                f"?symbols={symbol}")
        # Alpaca crypto data endpoint does not require auth, but we
        # pass headers when available for consistency.
        kwargs: dict[str, Any] = {"timeout": timeout_seconds}
        if headers is not None:
            kwargs["headers"] = headers
        r = requests.get(url, **kwargs)
        if r.status_code != 200:
            return MarketSnapshot(
                symbol=symbol, asset_class="crypto",
                timestamp=None, price=None,
                data_quality=PROVIDER_ERROR,
                error=f"HTTP {r.status_code}",
            )
        body = r.json() or {}
        quotes = body.get("quotes") or {}
        q = quotes.get(symbol) or {}
        bid = q.get("bp")
        ask = q.get("ap")
        ts_iso = q.get("t") or ""
        if bid is None and ask is None:
            return MarketSnapshot(
                symbol=symbol, asset_class="crypto",
                timestamp=None, price=None,
                data_quality=NO_MARKET_DATA,
                error="missing bid/ask in crypto quote",
            )
        try:
            bid_f = float(bid) if bid is not None else None
            ask_f = float(ask) if ask is not None else None
        except (TypeError, ValueError):
            return MarketSnapshot(
                symbol=symbol, asset_class="crypto",
                timestamp=None, price=None,
                data_quality=PROVIDER_ERROR,
                error="non-numeric bid/ask",
            )
        mid: float | None = None
        if bid_f and ask_f and bid_f > 0 and ask_f > 0:
            mid = round((bid_f + ask_f) / 2.0, 6)
        else:
            mid = bid_f or ask_f
        stale = _stale_seconds(ts_iso)
        quality = _grade_quality(stale, budget_seconds=stale_budget_seconds)
        return MarketSnapshot(
            symbol=symbol, asset_class="crypto",
            timestamp=_now() - (stale or 0.0),
            price=mid, bid=bid_f, ask=ask_f,
            data_quality=quality,
            stale_seconds=stale,
        )
    except Exception as e:
        return MarketSnapshot(
            symbol=symbol, asset_class="crypto",
            timestamp=None, price=None,
            data_quality=PROVIDER_ERROR,
            error=f"{type(e).__name__}: {e}",
        )


def fetch_snapshot(symbol: str, asset_class: str | None = None,
                    *,
                    stale_budget_seconds: float = DEFAULT_STALE_BUDGET_SECONDS,
                    timeout_seconds: float = 5.0) -> MarketSnapshot:
    """Dispatch helper. Picks equity vs crypto based on symbol shape."""
    if asset_class is None:
        if "/" in symbol or symbol.upper().endswith("USD"):
            asset_class = "crypto"
        else:
            asset_class = "us_equity"
    if asset_class == "crypto":
        return fetch_crypto_quote(
            symbol, stale_budget_seconds=stale_budget_seconds,
            timeout_seconds=timeout_seconds,
        )
    return fetch_equity_quote(
        symbol, stale_budget_seconds=stale_budget_seconds,
        timeout_seconds=timeout_seconds,
    )


def fetch_universe_snapshots(
    equity_symbols: tuple[str, ...] = DEFAULT_EQUITY_SYMBOLS,
    crypto_symbols: tuple[str, ...] = DEFAULT_CRYPTO_SYMBOLS,
    *,
    stale_budget_seconds: float = DEFAULT_STALE_BUDGET_SECONDS,
    timeout_seconds: float = 5.0,
) -> list[MarketSnapshot]:
    """Fetch a snapshot for every symbol in the universe.

    Pure aggregator. Errors per symbol surface as
    PROVIDER_ERROR / NO_MARKET_DATA on the individual snapshot; no
    aggregate raise.
    """
    out: list[MarketSnapshot] = []
    for sym in equity_symbols:
        out.append(fetch_equity_quote(
            sym, stale_budget_seconds=stale_budget_seconds,
            timeout_seconds=timeout_seconds,
        ))
    for sym in crypto_symbols:
        out.append(fetch_crypto_quote(
            sym, stale_budget_seconds=stale_budget_seconds,
            timeout_seconds=timeout_seconds,
        ))
    return out


def fetch_daily_bars(symbol: str, days: int = 35) -> list[dict] | None:
    """Thin re-export of ``shared/market_data.py::get_daily_bars``.

    Provided here so v3.27 shadow callers can import ALL market-data
    helpers from one module and never need ``shared/alpaca_orders.py``.
    """
    try:
        from market_data import get_daily_bars  # type: ignore
    except ImportError:
        from shared.market_data import get_daily_bars  # type: ignore
    try:
        return get_daily_bars(symbol, days=days)
    except Exception:
        return None


def policy_summary() -> dict[str, Any]:
    return {
        "version": "v3.27.0",
        "data_host": ALPACA_DATA_URL,
        "forbidden_broker_host": _FORBIDDEN_BROKER_HOST,
        "default_equity_universe": list(DEFAULT_EQUITY_SYMBOLS),
        "default_crypto_universe": list(DEFAULT_CRYPTO_SYMBOLS),
        "stale_budget_seconds": DEFAULT_STALE_BUDGET_SECONDS,
        "data_qualities": sorted(ALL_DATA_QUALITIES),
        "invariants": {
            "NEVER_SUBMITS_ORDERS": NEVER_SUBMITS_ORDERS,
            "NEVER_TOUCHES_BROKER_HOST": NEVER_TOUCHES_BROKER_HOST,
            "NEVER_IMPORTS_ALPACA_ORDERS": NEVER_IMPORTS_ALPACA_ORDERS,
            "NEVER_FABRICATES_PRICE": NEVER_FABRICATES_PRICE,
        },
    }


__all__ = [
    # Enum
    "REAL_MARKET_DATA", "NO_MARKET_DATA",
    "STALE_MARKET_DATA", "PROVIDER_ERROR",
    "ALL_DATA_QUALITIES",
    # Invariants
    "NEVER_SUBMITS_ORDERS",
    "NEVER_TOUCHES_BROKER_HOST",
    "NEVER_IMPORTS_ALPACA_ORDERS",
    "NEVER_FABRICATES_PRICE",
    # Constants
    "ALPACA_DATA_URL",
    "DEFAULT_EQUITY_SYMBOLS", "DEFAULT_CRYPTO_SYMBOLS",
    "DEFAULT_STALE_BUDGET_SECONDS",
    # Data class
    "MarketSnapshot",
    # API
    "fetch_equity_quote", "fetch_crypto_quote",
    "fetch_snapshot", "fetch_universe_snapshots",
    "fetch_daily_bars",
    "policy_summary",
]
