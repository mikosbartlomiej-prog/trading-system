"""shared/pretrade_snapshot.py — single lightweight pre-trade state snapshot.

v3.10 (2026-05-27): consolidates 4 separate Alpaca GETs (account, positions,
orders, governor) into ONE cached snapshot per cron-run.

PROBLEM SOLVED:
Before v3.10, every monitor independently called:
  - get_account_status()        → 1 Alpaca GET /v2/account
  - has_open_position(symbol)   → 1 Alpaca GET /v2/positions/{symbol}
  - check open orders           → 1 Alpaca GET /v2/orders
  - intraday_governor.snapshot  → reads runtime_state.json
On a typical entry tick (price-monitor + crypto-monitor + defense-monitor +
twitter-monitor running parallel), this = ~12-20 Alpaca calls per minute.
Alpaca paper rate limit is 200/min; we were running at ~30% headroom on
quiet days. During high-activity windows we'd hit the wall.

USAGE (in monitor):
    from pretrade_snapshot import get_snapshot, classify_snapshot_for_intraday
    snap = get_snapshot()                    # cached 30s, instant after first call
    if snap.is_unavailable():
        return defer("snapshot_unavailable", retry_after_s=60)
    # Now use snap.equity, snap.positions, snap.has_position(sym), etc.

ARCHITECTURE:
- Singleton cache in module scope (per-process; each cron run = fresh process)
- TTL 30s (long enough for one tick's downstream calls; short enough to not
  miss intraday state changes)
- Fail-soft: if Alpaca unavailable, snapshot.unavailable=True; monitors decide
  DEFER vs DOWNSIZE vs BLOCK per their own policy
- Zero state mutation — pure read

POLICY MAPPING (snapshot completeness → verdict):
  Full data (account + positions + orders) → ALLOW for risk decisions
  Account OK, positions/orders fail        → DOWNSIZE (50%) — partial visibility
  Account fail                             → DEFER (next cron, account is critical)
  paper-only invariant violated            → BLOCK (never operate on non-paper)
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

# Module-level cache (singleton per-process)
_SNAPSHOT_CACHE: dict[str, object] = {"snapshot": None, "ts": 0.0}
_SNAPSHOT_TTL_S = 30.0


ALPACA_BASE_URL = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID":     os.environ.get("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.environ.get("ALPACA_SECRET_KEY", ""),
    }


# Paper-only invariant — checked once per snapshot fetch
PAPER_BASE = "https://paper-api.alpaca.markets"


@dataclass
class PreTradeSnapshot:
    """Frozen view of system state at one moment, for pipeline-wide reuse."""

    # Account
    account: Optional[dict] = None
    equity: float = 0.0
    cash: float = 0.0
    buying_power: float = 0.0
    daily_pl_pct: float = 0.0
    daytrade_count: int = 0
    pattern_day_trader: bool = False
    account_blocked: bool = False
    trading_blocked: bool = False

    # Positions (list of dicts) + lookup by symbol
    positions: list[dict] = field(default_factory=list)
    _position_by_symbol: dict[str, dict] = field(default_factory=dict)

    # Open orders (list of dicts)
    open_orders: list[dict] = field(default_factory=list)

    # Governor state (FSM + max_gross_target)
    intraday_fsm: str = "FLAT"
    intraday_max_gross: float = 1.5
    intraday_pnl: float = 0.0
    intraday_peak_pnl: float = 0.0

    # Snapshot metadata
    fetched_at: float = field(default_factory=time.time)
    paper_only_ok: bool = True
    account_unavailable: bool = False
    positions_unavailable: bool = False
    orders_unavailable: bool = False
    errors: list[str] = field(default_factory=list)

    def is_unavailable(self) -> bool:
        """True if critical data missing (account). Use to gate ALLOW vs DEFER."""
        return self.account_unavailable

    def is_partial(self) -> bool:
        """True if account OK but positions or orders missing.
        Caller decides DOWNSIZE vs ALLOW."""
        return (not self.account_unavailable
                and (self.positions_unavailable or self.orders_unavailable))

    def has_position(self, symbol: str) -> bool:
        return symbol.upper() in self._position_by_symbol

    def get_position(self, symbol: str) -> Optional[dict]:
        return self._position_by_symbol.get(symbol.upper())

    def open_orders_for(self, symbol: str, side: Optional[str] = None) -> list[dict]:
        sym = symbol.upper()
        out = [o for o in self.open_orders if (o.get("symbol") or "").upper() == sym]
        if side:
            out = [o for o in out if (o.get("side") or "").lower() == side.lower()]
        return out

    def position_value(self, symbol: str) -> float:
        p = self.get_position(symbol)
        if not p:
            return 0.0
        try:
            return abs(float(p.get("market_value") or 0))
        except (ValueError, TypeError):
            return 0.0

    def position_pct_equity(self, symbol: str) -> float:
        if self.equity <= 0:
            return 0.0
        return self.position_value(symbol) / self.equity * 100.0

    def to_summary(self) -> dict:
        return {
            "equity": self.equity,
            "cash": self.cash,
            "buying_power": self.buying_power,
            "daily_pl_pct": self.daily_pl_pct,
            "daytrade_count": self.daytrade_count,
            "positions_count": len(self.positions),
            "open_orders_count": len(self.open_orders),
            "intraday_fsm": self.intraday_fsm,
            "intraday_pnl": self.intraday_pnl,
            "paper_only_ok": self.paper_only_ok,
            "account_unavailable": self.account_unavailable,
            "positions_unavailable": self.positions_unavailable,
            "orders_unavailable": self.orders_unavailable,
            "errors": self.errors,
            "fetched_at": self.fetched_at,
        }


def _fetch_account() -> Optional[dict]:
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/v2/account",
                         headers=_headers(), timeout=8)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _fetch_positions() -> Optional[list[dict]]:
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/v2/positions",
                         headers=_headers(), timeout=8)
        if r.status_code == 200:
            return r.json() or []
    except Exception:
        pass
    return None


def _fetch_open_orders() -> Optional[list[dict]]:
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/v2/orders",
                         headers=_headers(),
                         params={"status": "open", "limit": 200},
                         timeout=8)
        if r.status_code == 200:
            return r.json() or []
    except Exception:
        pass
    return None


def _fetch_governor_state() -> dict:
    """Read learning-loop/runtime_state.json::intraday_governor (local file)."""
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "learning-loop" / "runtime_state.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("intraday_governor", {}) or {}
    except Exception:
        return {}


def _build_snapshot() -> PreTradeSnapshot:
    """Build a fresh snapshot from all sources. Pure I/O — no caching here."""
    snap = PreTradeSnapshot()

    # Paper-only invariant check
    if ALPACA_BASE_URL.strip().rstrip("/") != PAPER_BASE:
        snap.paper_only_ok = False
        snap.errors.append(f"non-paper endpoint: {ALPACA_BASE_URL}")
        return snap

    # Account (critical)
    acct = _fetch_account()
    if not acct:
        snap.account_unavailable = True
        snap.errors.append("account_fetch_failed")
    else:
        snap.account = acct
        try:
            snap.equity = float(acct.get("equity") or 0)
            snap.cash = float(acct.get("cash") or 0)
            snap.buying_power = float(acct.get("buying_power") or 0)
            last_eq = float(acct.get("last_equity") or snap.equity)
            snap.daily_pl_pct = (
                ((snap.equity - last_eq) / last_eq * 100) if last_eq > 0 else 0.0
            )
            snap.daytrade_count = int(acct.get("daytrade_count") or 0)
            snap.pattern_day_trader = bool(acct.get("pattern_day_trader"))
            snap.account_blocked = bool(acct.get("account_blocked"))
            snap.trading_blocked = bool(acct.get("trading_blocked"))
        except (ValueError, TypeError) as e:
            snap.errors.append(f"account_parse_error: {e}")

    # Positions (non-critical — partial OK)
    pos = _fetch_positions()
    if pos is None:
        snap.positions_unavailable = True
        snap.errors.append("positions_fetch_failed")
    else:
        snap.positions = pos
        snap._position_by_symbol = {
            (p.get("symbol") or "").upper(): p for p in pos
        }

    # Open orders (non-critical — partial OK)
    orders = _fetch_open_orders()
    if orders is None:
        snap.orders_unavailable = True
        snap.errors.append("orders_fetch_failed")
    else:
        snap.open_orders = orders

    # Intraday governor state (local file — almost never fails)
    gov = _fetch_governor_state()
    snap.intraday_fsm = gov.get("pnl_state") or "FLAT"
    snap.intraday_max_gross = float(gov.get("max_gross_target") or 1.5)
    snap.intraday_pnl = float(gov.get("current_intraday_pnl") or 0)
    snap.intraday_peak_pnl = float(gov.get("intraday_peak_pnl") or 0)

    return snap


def get_snapshot(force_refresh: bool = False) -> PreTradeSnapshot:
    """Return cached snapshot if <TTL old, else fetch fresh.

    Used by all risk gates + monitors. Should be the ONLY source of Alpaca
    account/positions/orders data in the pipeline (per cron run).

    force_refresh=True bypasses cache (useful for tests or post-order updates).
    """
    now = time.time()
    cached = _SNAPSHOT_CACHE.get("snapshot")
    age = now - float(_SNAPSHOT_CACHE.get("ts") or 0)
    if not force_refresh and cached is not None and age < _SNAPSHOT_TTL_S:
        return cached  # type: ignore

    fresh = _build_snapshot()
    _SNAPSHOT_CACHE["snapshot"] = fresh
    _SNAPSHOT_CACHE["ts"] = now
    return fresh


def clear_snapshot_cache() -> None:
    """For tests. In production, cache lives only for the cron-run lifetime."""
    _SNAPSHOT_CACHE["snapshot"] = None
    _SNAPSHOT_CACHE["ts"] = 0.0


# ─── Policy helper: snapshot → RiskVerdict ────────────────────────────────────

def classify_snapshot_for_intraday(snap: PreTradeSnapshot):
    """Map snapshot completeness to intraday risk verdict.

    Returns a RiskDecision. Caller should respect verdict:
      BLOCK     — paper invariant violated; never operate
      DEFER     — account unavailable; retry next cron
      DOWNSIZE  — partial data (positions/orders missing); reduce size
      ALLOW     — full data + no account-level issues
    """
    try:
        from risk_classification import block, defer, downsize, allow
    except ImportError:
        from shared.risk_classification import block, defer, downsize, allow  # type: ignore

    if not snap.paper_only_ok:
        return block("paper-only invariant violated", gate="pretrade_snapshot",
                     errors=snap.errors)
    if snap.account_blocked or snap.trading_blocked:
        return block(
            f"account_blocked={snap.account_blocked} trading_blocked={snap.trading_blocked}",
            gate="pretrade_snapshot",
        )
    if snap.account_unavailable:
        return defer("account_fetch_failed — retry next cron",
                     gate="pretrade_snapshot", retry_after_s=60,
                     errors=snap.errors)
    if snap.is_partial():
        return downsize(
            "snapshot partial (positions/orders fetch failed); reducing size 0.5×",
            size_multiplier=0.5, gate="pretrade_snapshot",
            positions_unavailable=snap.positions_unavailable,
            orders_unavailable=snap.orders_unavailable,
        )
    return allow("snapshot complete", gate="pretrade_snapshot",
                 equity=snap.equity, positions=len(snap.positions))
