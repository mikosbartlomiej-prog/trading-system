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

# ─── v3.27.1 diagnostic status tokens (narrower than data_quality) ───────────
#
# These distinguish failure modes the operator must see in the
# workflow health doc. A single snapshot has ONE data_quality and
# ONE status_token. Every code path that returns NO_MARKET_DATA /
# PROVIDER_ERROR / STALE attaches the corresponding token.

MARKET_DATA_CREDENTIALS_MISSING            = "MARKET_DATA_CREDENTIALS_MISSING"
MARKET_DATA_AUTH_FAILED                    = "MARKET_DATA_AUTH_FAILED"
MARKET_DATA_PROVIDER_ERROR                 = "MARKET_DATA_PROVIDER_ERROR"
MARKET_DATA_EMPTY_RESPONSE                 = "MARKET_DATA_EMPTY_RESPONSE"
MARKET_CLOSED_OR_NO_BARS                   = "MARKET_CLOSED_OR_NO_BARS"
MARKET_DATA_STALE                          = "MARKET_DATA_STALE"
INSUFFICIENT_BARS_FOR_SIGNAL               = "INSUFFICIENT_BARS_FOR_SIGNAL"
REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL   = "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL"
REAL_MARKET_SIGNAL_RECORDS_EMITTED         = "REAL_MARKET_SIGNAL_RECORDS_EMITTED"

ALL_STATUS_TOKENS: frozenset[str] = frozenset({
    MARKET_DATA_CREDENTIALS_MISSING,
    MARKET_DATA_AUTH_FAILED,
    MARKET_DATA_PROVIDER_ERROR,
    MARKET_DATA_EMPTY_RESPONSE,
    MARKET_CLOSED_OR_NO_BARS,
    MARKET_DATA_STALE,
    INSUFFICIENT_BARS_FOR_SIGNAL,
    REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL,
    REAL_MARKET_SIGNAL_RECORDS_EMITTED,
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
    # v3.27.1 — granular diagnostic token (one of ALL_STATUS_TOKENS).
    # Optional during the v3.27.0 → v3.27.1 transition; callers that
    # leave it as None get a safe NO_SIGNAL default in aggregation.
    status_token: str | None = None

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
            "status_token": self.status_token,
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
            status_token=MARKET_DATA_CREDENTIALS_MISSING,
        )
    try:
        import requests
        url = (f"{ALPACA_DATA_URL}/v2/stocks/{symbol}/quotes/latest"
                f"?feed=iex")
        r = requests.get(url, headers=headers, timeout=timeout_seconds)
        if r.status_code != 200:
            # v3.27.1: 401/403 → AUTH_FAILED; anything else → PROVIDER_ERROR
            token = (MARKET_DATA_AUTH_FAILED
                      if r.status_code in (401, 403)
                      else MARKET_DATA_PROVIDER_ERROR)
            return MarketSnapshot(
                symbol=symbol, asset_class="us_equity",
                timestamp=None, price=None,
                data_quality=PROVIDER_ERROR,
                error=f"HTTP {r.status_code}",
                status_token=token,
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
                status_token=MARKET_DATA_EMPTY_RESPONSE,
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
                status_token=MARKET_DATA_PROVIDER_ERROR,
            )
        mid: float | None = None
        if bid_f and ask_f and bid_f > 0 and ask_f > 0:
            mid = round((bid_f + ask_f) / 2.0, 4)
        else:
            mid = bid_f or ask_f
        stale = _stale_seconds(ts_iso)
        quality = _grade_quality(stale, budget_seconds=stale_budget_seconds)
        # v3.27.1: token reflects quality at provider layer; the
        # generator will upgrade to SIGNAL_RECORDS_EMITTED when a
        # signal fires.
        if quality == REAL_MARKET_DATA:
            token = REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL
        elif quality == STALE_MARKET_DATA:
            token = MARKET_DATA_STALE
        else:
            token = MARKET_DATA_PROVIDER_ERROR
        return MarketSnapshot(
            symbol=symbol, asset_class="us_equity",
            timestamp=_now() - (stale or 0.0),
            price=mid, bid=bid_f, ask=ask_f,
            data_quality=quality,
            stale_seconds=stale,
            status_token=token,
        )
    except Exception as e:
        return MarketSnapshot(
            symbol=symbol, asset_class="us_equity",
            timestamp=None, price=None,
            data_quality=PROVIDER_ERROR,
            error=f"{type(e).__name__}: {e}",
            status_token=MARKET_DATA_PROVIDER_ERROR,
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
            token = (MARKET_DATA_AUTH_FAILED
                      if r.status_code in (401, 403)
                      else MARKET_DATA_PROVIDER_ERROR)
            return MarketSnapshot(
                symbol=symbol, asset_class="crypto",
                timestamp=None, price=None,
                data_quality=PROVIDER_ERROR,
                error=f"HTTP {r.status_code}",
                status_token=token,
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
                status_token=MARKET_DATA_EMPTY_RESPONSE,
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
                status_token=MARKET_DATA_PROVIDER_ERROR,
            )
        mid: float | None = None
        if bid_f and ask_f and bid_f > 0 and ask_f > 0:
            mid = round((bid_f + ask_f) / 2.0, 6)
        else:
            mid = bid_f or ask_f
        stale = _stale_seconds(ts_iso)
        quality = _grade_quality(stale, budget_seconds=stale_budget_seconds)
        if quality == REAL_MARKET_DATA:
            token = REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL
        elif quality == STALE_MARKET_DATA:
            token = MARKET_DATA_STALE
        else:
            token = MARKET_DATA_PROVIDER_ERROR
        return MarketSnapshot(
            symbol=symbol, asset_class="crypto",
            timestamp=_now() - (stale or 0.0),
            price=mid, bid=bid_f, ask=ask_f,
            data_quality=quality,
            stale_seconds=stale,
            status_token=token,
        )
    except Exception as e:
        return MarketSnapshot(
            symbol=symbol, asset_class="crypto",
            timestamp=None, price=None,
            data_quality=PROVIDER_ERROR,
            error=f"{type(e).__name__}: {e}",
            status_token=MARKET_DATA_PROVIDER_ERROR,
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


# ─── v3.22 per-symbol diagnostic categorisation ──────────────────────────────
#
# `fetch_universe_snapshots_with_diagnostics` returns the same list of
# snapshots PLUS an aggregate Counter of diagnostic tokens so the
# operator can tell at a glance whether a thin evidence day is a
# strategy problem or a data problem.

DIAG_OK             = "OK"
DIAG_AUTH_MISSING   = "AUTH_MISSING"
DIAG_AUTH_FAILED    = "AUTH_FAILED"
DIAG_BARS_EMPTY     = "BARS_EMPTY"
DIAG_INVALID_SYMBOL = "INVALID_SYMBOL"
DIAG_RATE_LIMIT     = "RATE_LIMIT"
DIAG_STALE          = "STALE"
DIAG_PROVIDER_ERROR = "PROVIDER_ERROR"
DIAG_OTHER          = "OTHER"

ALL_DIAG_TOKENS: frozenset[str] = frozenset({
    DIAG_OK, DIAG_AUTH_MISSING, DIAG_AUTH_FAILED, DIAG_BARS_EMPTY,
    DIAG_INVALID_SYMBOL, DIAG_RATE_LIMIT, DIAG_STALE,
    DIAG_PROVIDER_ERROR, DIAG_OTHER,
})


@dataclass
class UniverseFetchResult:
    """Return type for v3.22 diagnostic fetch.

    ``snapshots`` is the same list ``fetch_universe_snapshots`` returns,
    so callers that just want quotes can ignore the diagnostic counter.

    ``diagnostic_token_counts`` is a ``dict[str, int]`` keyed by the
    DIAG_* tokens above. Use it for the shadow-runner per-cycle report
    or the heartbeat freshness diagnostics.

    ``symbols_skipped_stale`` and ``symbols_skipped_provider_error`` are
    explicit per-bucket lists so the shadow runner can name the
    affected symbols in its report without re-walking the snapshots.
    """
    snapshots:                  list[MarketSnapshot]
    diagnostic_token_counts:    dict[str, int]
    symbols_skipped_stale:      list[str]
    symbols_skipped_provider_error: list[str]


def _classify_snapshot_diagnostic(snap: MarketSnapshot) -> str:
    """Map one MarketSnapshot to a single DIAG_* token."""
    err = (snap.error or "").lower()
    tok = snap.status_token or ""

    # Auth-related categorisation happens BEFORE we look at data_quality
    # because a credentials-missing snapshot will have data_quality
    # NO_MARKET_DATA but the cause is auth, not a data outage.
    if tok == MARKET_DATA_CREDENTIALS_MISSING or "not set" in err:
        return DIAG_AUTH_MISSING
    if tok == MARKET_DATA_AUTH_FAILED or "http 401" in err or "http 403" in err:
        return DIAG_AUTH_FAILED
    if "http 404" in err:
        return DIAG_INVALID_SYMBOL
    if "http 429" in err:
        return DIAG_RATE_LIMIT
    if "missing bid/ask" in err or tok == MARKET_DATA_EMPTY_RESPONSE:
        return DIAG_BARS_EMPTY
    if snap.data_quality == STALE_MARKET_DATA or tok == MARKET_DATA_STALE:
        return DIAG_STALE
    if snap.data_quality == PROVIDER_ERROR or tok == MARKET_DATA_PROVIDER_ERROR:
        return DIAG_PROVIDER_ERROR
    if snap.data_quality == REAL_MARKET_DATA:
        return DIAG_OK
    return DIAG_OTHER


def fetch_universe_snapshots_with_diagnostics(
    equity_symbols: tuple[str, ...] = DEFAULT_EQUITY_SYMBOLS,
    crypto_symbols: tuple[str, ...] = DEFAULT_CRYPTO_SYMBOLS,
    *,
    stale_budget_seconds: float = DEFAULT_STALE_BUDGET_SECONDS,
    timeout_seconds: float = 5.0,
) -> UniverseFetchResult:
    """Fetch the universe and bucket each snapshot into a DIAG_* token.

    NEVER raises. Catches every error inside the per-symbol fetch and
    surfaces it on the snapshot. The aggregate counter is built from
    the resulting snapshots so even a total outage (every symbol
    raises) still returns a populated counter.
    """
    snapshots: list[MarketSnapshot] = []

    # v3.22 contract: when credentials are missing, every symbol must
    # report NO_MARKET_DATA + CREDENTIALS_MISSING. The legacy crypto
    # fetcher tolerates missing creds; the diagnostics wrapper does
    # NOT, so the operator sees the auth gap up front instead of a
    # noisy provider error.
    if _headers() is None:
        for sym in equity_symbols:
            snapshots.append(MarketSnapshot(
                symbol=sym, asset_class="us_equity",
                timestamp=None, price=None,
                data_quality=NO_MARKET_DATA,
                error="ALPACA_API_KEY / ALPACA_SECRET_KEY not set",
                status_token=MARKET_DATA_CREDENTIALS_MISSING,
            ))
        for sym in crypto_symbols:
            snapshots.append(MarketSnapshot(
                symbol=sym, asset_class="crypto",
                timestamp=None, price=None,
                data_quality=NO_MARKET_DATA,
                error="ALPACA_API_KEY / ALPACA_SECRET_KEY not set",
                status_token=MARKET_DATA_CREDENTIALS_MISSING,
            ))
    else:
        try:
            snapshots = fetch_universe_snapshots(
                equity_symbols=equity_symbols,
                crypto_symbols=crypto_symbols,
                stale_budget_seconds=stale_budget_seconds,
                timeout_seconds=timeout_seconds,
            )
        except Exception:
            # Belt-and-braces: per-symbol fetches already swallow errors,
            # but if something genuinely upstream blows up we still want
            # a valid UniverseFetchResult.
            snapshots = []

    counts: dict[str, int] = {}
    stale_syms: list[str] = []
    err_syms: list[str] = []
    for snap in snapshots:
        tok = _classify_snapshot_diagnostic(snap)
        counts[tok] = counts.get(tok, 0) + 1
        if tok == DIAG_STALE:
            stale_syms.append(snap.symbol)
        if tok == DIAG_PROVIDER_ERROR:
            err_syms.append(snap.symbol)

    return UniverseFetchResult(
        snapshots=snapshots,
        diagnostic_token_counts=counts,
        symbols_skipped_stale=stale_syms,
        symbols_skipped_provider_error=err_syms,
    )


def _resolve_get_daily_bars():
    """Module-level injectable resolver for the bars-provider function.

    Centralises the dual-path import (``market_data`` vs
    ``shared.market_data``) so tests can patch a single, stable
    attribute on this module instead of guessing which module-object
    Python will resolve at import time.
    """
    try:
        from market_data import get_daily_bars  # type: ignore
    except ImportError:
        from shared.market_data import get_daily_bars  # type: ignore
    return get_daily_bars


def fetch_daily_bars(symbol: str, days: int = 35) -> list[dict] | None:
    """Thin re-export of ``shared/market_data.py::get_daily_bars``.

    Provided here so v3.27 shadow callers can import ALL market-data
    helpers from one module and never need the broker-orders module.
    """
    try:
        return _resolve_get_daily_bars()(symbol, days=days)
    except Exception:
        return None


def fetch_daily_bars_diagnostic(
    symbol: str, days: int = 35,
) -> tuple[list[dict] | None, str]:
    """v3.27.1 — fetch daily bars and return (bars, status_token).

    Distinguishes the diagnostic failure modes that
    ``fetch_daily_bars`` silently coalesced to ``None``:
    - missing credentials → MARKET_DATA_CREDENTIALS_MISSING
    - empty payload → MARKET_CLOSED_OR_NO_BARS
    - exception → MARKET_DATA_PROVIDER_ERROR
    - too few bars → INSUFFICIENT_BARS_FOR_SIGNAL
    - happy path → REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL
    """
    key = os.environ.get("ALPACA_API_KEY")
    sec = os.environ.get("ALPACA_SECRET_KEY")
    if not key or not sec:
        return None, MARKET_DATA_CREDENTIALS_MISSING
    try:
        bars = _resolve_get_daily_bars()(symbol, days=days)
    except Exception:
        return None, MARKET_DATA_PROVIDER_ERROR
    if bars is None or len(bars) == 0:
        return None, MARKET_CLOSED_OR_NO_BARS
    if len(bars) < 22:
        # Provider returned bars but not enough for ATR-window signals.
        return bars, INSUFFICIENT_BARS_FOR_SIGNAL
    return bars, REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL


def policy_summary() -> dict[str, Any]:
    return {
        "version": "v3.27.1",
        "data_host": ALPACA_DATA_URL,
        "forbidden_broker_host": _FORBIDDEN_BROKER_HOST,
        "default_equity_universe": list(DEFAULT_EQUITY_SYMBOLS),
        "default_crypto_universe": list(DEFAULT_CRYPTO_SYMBOLS),
        "stale_budget_seconds": DEFAULT_STALE_BUDGET_SECONDS,
        "data_qualities": sorted(ALL_DATA_QUALITIES),
        "status_tokens": sorted(ALL_STATUS_TOKENS),
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
    # v3.27.1 diagnostic status tokens
    "MARKET_DATA_CREDENTIALS_MISSING",
    "MARKET_DATA_AUTH_FAILED",
    "MARKET_DATA_PROVIDER_ERROR",
    "MARKET_DATA_EMPTY_RESPONSE",
    "MARKET_CLOSED_OR_NO_BARS",
    "MARKET_DATA_STALE",
    "INSUFFICIENT_BARS_FOR_SIGNAL",
    "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL",
    "REAL_MARKET_SIGNAL_RECORDS_EMITTED",
    "ALL_STATUS_TOKENS",
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
    "fetch_daily_bars", "fetch_daily_bars_diagnostic",
    "policy_summary",
]
