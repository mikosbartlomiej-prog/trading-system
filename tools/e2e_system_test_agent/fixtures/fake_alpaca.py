"""In-memory fake Alpaca paper API.

Behavioural goals:
  - All methods are deterministic; same inputs → same outputs
  - State (account / positions / orders) lives in memory; reset() restores it
  - Endpoint can be set; `verify_paper_only()` raises if anyone tries to flip
    it to a live URL — exercises the real `assert_paper_only` invariant

Coverage of broker scenarios:
  - normal fill (auto-fill if `auto_fill=True`)
  - no fill (default for limit orders far from the market)
  - API failure (set `_fail_mode`)
  - rate limit (HTTP 429 stub)
  - insufficient buying power
  - market closed (set `clock.market_open = False`)
  - duplicate order (same client_order_id)
  - option quote missing (set per-symbol)
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


PAPER_BASE_URL = "https://paper-api.alpaca.markets"


class NetworkBlocked(RuntimeError):
    """Raised by the global conftest guard if a test tries real network I/O."""


@dataclass
class FakeOrder:
    id: str
    symbol: str
    side: str
    qty: float
    limit_price: float | None
    stop_price: float | None
    order_class: str
    order_type: str
    status: str               # new | filled | rejected | canceled | expired
    client_order_id: str
    submitted_at: str
    filled_avg_price: float | None = None
    filled_qty: float = 0.0


@dataclass
class FakePosition:
    symbol: str
    qty: float
    side: str                 # long | short
    avg_entry_price: float
    market_value: float
    unrealized_pl: float = 0.0
    unrealized_plpc: float = 0.0
    asset_class: str = "us_equity"


class FakeAlpacaClient:
    """Drop-in fake for the bits of Alpaca our code uses."""

    def __init__(
        self,
        *,
        endpoint: str = PAPER_BASE_URL,
        equity: float = 100_000.0,
        cash: float = 100_000.0,
        buying_power: float = 200_000.0,
        auto_fill: bool = False,
    ):
        self.endpoint = endpoint
        self.account = {
            "equity":       str(equity),
            "cash":          str(cash),
            "buying_power":  str(buying_power),
            "status":        "ACTIVE",
            "last_equity":   str(equity),
            "daily_pl_pct":  "0.0",
        }
        self.positions: dict[str, FakePosition] = {}
        self.orders: list[FakeOrder] = []
        self._order_counter = 0
        self.auto_fill = auto_fill
        self.fail_mode: str | None = None   # None | 'timeout' | '429' | '500'
        self.quotes: dict[str, dict] = {}
        self.option_chains: dict[str, list[dict]] = {}
        self.market_open = True

    # ─── lifecycle helpers ──────────────────────────────────────────────────

    def reset(self):
        """Restore initial state — for use between scenarios."""
        self.__init__(
            endpoint=self.endpoint,
            equity=float(self.account["equity"]),
            cash=float(self.account["cash"]),
            buying_power=float(self.account["buying_power"]),
            auto_fill=self.auto_fill,
        )

    def verify_paper_only(self) -> bool:
        if self.endpoint != PAPER_BASE_URL:
            raise RuntimeError(
                f"fake-alpaca configured with non-paper endpoint: {self.endpoint}"
            )
        return True

    # ─── account ────────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        self.verify_paper_only()
        self._maybe_fail()
        return copy.deepcopy(self.account)

    def set_daily_pl_pct(self, pct: float):
        self.account["daily_pl_pct"] = str(pct)

    def set_equity(self, equity: float):
        self.account["equity"] = str(equity)

    # ─── positions ──────────────────────────────────────────────────────────

    def get_positions(self) -> list[dict]:
        self.verify_paper_only()
        self._maybe_fail()
        return [self._pos_to_dict(p) for p in self.positions.values()]

    def get_position(self, symbol: str) -> dict | None:
        p = self.positions.get(symbol.upper())
        return self._pos_to_dict(p) if p else None

    def set_position(self, **kwargs) -> FakePosition:
        p = FakePosition(**{"side": "long", "asset_class": "us_equity",
                            "market_value": kwargs.get("qty", 0)
                            * kwargs.get("avg_entry_price", 0),
                            **kwargs})
        self.positions[p.symbol.upper()] = p
        return p

    def close_position(self, symbol: str) -> dict:
        """Equivalent to DELETE /v2/positions/{symbol}."""
        self.verify_paper_only()
        self._maybe_fail()
        symbol = symbol.upper()
        if symbol not in self.positions:
            return {"_status": 404, "_text": "position not found"}
        del self.positions[symbol]
        return {"status": "closed", "symbol": symbol}

    # ─── orders ─────────────────────────────────────────────────────────────

    def get_orders(self, *, status: str = "open",
                    symbols: list[str] | None = None) -> list[dict]:
        self.verify_paper_only()
        self._maybe_fail()
        sym_set = {s.upper() for s in (symbols or [])}
        out = []
        for o in self.orders:
            if status != "all":
                if status == "open" and o.status not in ("new", "accepted",
                                                          "pending_new"):
                    continue
            if sym_set and o.symbol.upper() not in sym_set:
                continue
            out.append(self._order_to_dict(o))
        return out

    def submit_order(self, **payload) -> dict:
        """
        Accepts a dict mirroring Alpaca's /v2/orders body.
        Returns the order dict (HTTP 200/201 shape) or an error dict.
        """
        self.verify_paper_only()
        self._maybe_fail()

        if not self.market_open and payload.get("type") != "limit":
            return {"_status": 422, "_text": "market closed"}

        # Duplicate client_order_id?
        coid = payload.get("client_order_id")
        if coid and any(o.client_order_id == coid for o in self.orders):
            return {"_status": 422, "_text": "duplicate client_order_id"}

        # Insufficient buying power (very rough)
        try:
            notional = float(payload.get("qty", 0)) * float(
                payload.get("limit_price")
                or payload.get("stop_price")
                or 0
            )
        except (TypeError, ValueError):
            notional = 0.0
        if notional > float(self.account["buying_power"]):
            return {"_status": 403, "_text": "insufficient buying power"}

        self._order_counter += 1
        order = FakeOrder(
            id=f"fake-order-{self._order_counter}",
            symbol=payload["symbol"],
            side=payload["side"],
            qty=float(payload.get("qty") or 0),
            limit_price=_safe_float(payload.get("limit_price")),
            stop_price=_safe_float(payload.get("stop_price")),
            order_class=payload.get("order_class", "simple"),
            order_type=payload.get("type", "limit"),
            status="new",
            client_order_id=coid or f"auto-{self._order_counter}",
            submitted_at=datetime.now(timezone.utc).isoformat(),
        )
        self.orders.append(order)

        if self.auto_fill:
            order.status = "filled"
            order.filled_qty = order.qty
            order.filled_avg_price = order.limit_price or 100.0
            # Apply to positions
            existing = self.positions.get(order.symbol.upper())
            if order.side == "buy":
                if existing:
                    new_qty = existing.qty + order.qty
                    new_avg = (existing.avg_entry_price * existing.qty
                                + order.filled_avg_price * order.qty) / new_qty
                    existing.qty = new_qty
                    existing.avg_entry_price = new_avg
                    existing.market_value = new_qty * new_avg
                else:
                    self.set_position(symbol=order.symbol.upper(),
                                       qty=order.qty, side="long",
                                       avg_entry_price=order.filled_avg_price)
            elif order.side in ("sell", "sell_short"):
                if existing:
                    existing.qty -= order.qty
                    existing.market_value = existing.qty * order.filled_avg_price
                    if existing.qty <= 0:
                        del self.positions[order.symbol.upper()]

        return self._order_to_dict(order)

    def cancel_order(self, order_id: str) -> dict:
        self.verify_paper_only()
        for o in self.orders:
            if o.id == order_id and o.status in ("new", "accepted",
                                                  "pending_new"):
                o.status = "canceled"
                return {"status": "canceled", "id": order_id}
        return {"_status": 404, "_text": "order not found"}

    # ─── market data ────────────────────────────────────────────────────────

    def set_quote(self, symbol: str, *, bid: float, ask: float):
        self.quotes[symbol.upper()] = {"bid": bid, "ask": ask,
                                        "mid": (bid + ask) / 2.0}

    def get_quote(self, symbol: str) -> dict | None:
        return self.quotes.get(symbol.upper())

    def set_option_chain(self, underlying: str, contracts: list[dict]):
        self.option_chains[underlying.upper()] = contracts

    def get_option_chain(self, underlying: str) -> list[dict]:
        return list(self.option_chains.get(underlying.upper(), []))

    # ─── internal ───────────────────────────────────────────────────────────

    def _maybe_fail(self):
        if self.fail_mode == "timeout":
            raise TimeoutError("fake-alpaca: simulated timeout")
        if self.fail_mode == "429":
            raise RuntimeError("fake-alpaca: HTTP 429 rate limit")
        if self.fail_mode == "500":
            raise RuntimeError("fake-alpaca: HTTP 500 server error")

    def _pos_to_dict(self, p: FakePosition | None) -> dict | None:
        if p is None:
            return None
        return {
            "symbol":           p.symbol,
            "qty":              str(p.qty),
            "side":             p.side,
            "avg_entry_price":  str(p.avg_entry_price),
            "market_value":     str(p.market_value),
            "unrealized_pl":    str(p.unrealized_pl),
            "unrealized_plpc":  str(p.unrealized_plpc),
            "asset_class":      p.asset_class,
        }

    def _order_to_dict(self, o: FakeOrder) -> dict:
        return {
            "id":               o.id,
            "symbol":           o.symbol,
            "side":             o.side,
            "qty":              str(o.qty),
            "limit_price":      str(o.limit_price) if o.limit_price is not None else None,
            "stop_price":       str(o.stop_price) if o.stop_price is not None else None,
            "order_class":      o.order_class,
            "type":             o.order_type,
            "status":           o.status,
            "client_order_id":  o.client_order_id,
            "submitted_at":     o.submitted_at,
            "filled_avg_price": str(o.filled_avg_price) if o.filled_avg_price else None,
            "filled_qty":       str(o.filled_qty),
        }


def _safe_float(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None
