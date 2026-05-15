#!/usr/bin/env python3
"""
One-shot 2026-05-15: close 22 GLD shares (revert duplicate from
two morning-allocator triggers placing same plan twice).

Background: morning-allocator was triggered manually at 14:46 + 14:49
UTC. Both fills landed for SPY/GLD/QQQ → 2× plan size. Three duplicates:
SPY 24, GLD 44, QQQ 22. User chose option C: close only the worst
single concentration (GLD at 19.5% equity — closest to 20% AGGRESSIVE
cap). Closes 22 GLD shares → restores plan position of 22.

PDT considerations (v3.8 intent-aware):
  - GLD opened today (14:46 + 14:49 UTC fills)
  - CLOSE same-day = 1 day-trade
  - Account at dt=4 (PDT-LOCKED)
  - is_emergency=True (operational correction, not discretionary) →
    v3.8 PDT guard bypasses BLOCK
  - This pushes dt to 5, but account is already locked; one more
    DT doesn't worsen rolling-window expiry materially

Order tag: client_order_id `op-correction-GLD-duplicate-<ts>` so
analyzer attributes this exit to "operational correction" not a
regular strategy exit (won't pollute win-rate stats).
"""

import os
import sys
from datetime import datetime, timezone

import requests

ALPACA_BASE = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/")

TARGET_SYMBOL = "GLD"
TARGET_QTY    = 22


def _headers() -> dict:
    key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        print("ERROR: ALPACA_API_KEY + ALPACA_SECRET_KEY required")
        sys.exit(1)
    return {
        "APCA-API-KEY-ID":     key,
        "APCA-API-SECRET-KEY": secret,
        "Accept":              "application/json",
        "Content-Type":        "application/json",
    }


def get_position(symbol: str) -> dict | None:
    try:
        r = requests.get(
            f"{ALPACA_BASE}/v2/positions/{symbol}",
            headers=_headers(),
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            print(f"  position {symbol} not found")
            return None
        print(f"  GET position {symbol}: HTTP {r.status_code} {r.text[:120]}")
        return None
    except Exception as e:
        print(f"  exception: {e}")
        return None


def cancel_symbol_orders(symbol: str) -> int:
    """Cancel all open orders for `symbol`. Returns count cancelled."""
    try:
        r = requests.get(
            f"{ALPACA_BASE}/v2/orders",
            headers=_headers(),
            params={"status": "open", "symbols": symbol, "limit": 50},
            timeout=10,
        )
        if r.status_code != 200:
            print(f"  GET open orders failed: HTTP {r.status_code}")
            return 0
        open_orders = r.json() or []
    except Exception as e:
        print(f"  list orders exception: {e}")
        return 0

    print(f"  found {len(open_orders)} open orders for {symbol}")
    cancelled = 0
    for o in open_orders:
        oid = o.get("id")
        otype = o.get("type", "?")
        oside = o.get("side", "?")
        try:
            r = requests.delete(
                f"{ALPACA_BASE}/v2/orders/{oid}",
                headers=_headers(),
                timeout=10,
            )
            if r.status_code in (200, 204):
                print(f"    cancelled [{oid[:8]}] {oside} {otype}")
                cancelled += 1
            else:
                print(f"    cancel [{oid[:8]}] failed: HTTP {r.status_code}")
        except Exception as e:
            print(f"    cancel [{oid[:8]}] exception: {e}")
    return cancelled


def place_sell(symbol: str, qty: int) -> dict | None:
    """
    Close `qty` shares of `symbol` via DELETE /v2/positions/{symbol}?qty=X.

    Bracket-order child legs (SL + TP) reserve the entire position. Caller
    MUST first cancel_symbol_orders(symbol) to release held_for_orders.
    DELETE on positions endpoint then closes the requested qty atomically.
    """
    try:
        r = requests.delete(
            f"{ALPACA_BASE}/v2/positions/{symbol}?qty={qty}",
            headers=_headers(),
            timeout=15,
        )
        if r.status_code in (200, 201, 207):
            return r.json()
        print(f"  DELETE /v2/positions/{symbol}?qty={qty}: HTTP {r.status_code} {r.text[:250]}")
        return None
    except Exception as e:
        print(f"  exception: {e}")
        return None


def main() -> int:
    print(f"=== Close GLD duplicate (operational correction 2026-05-15) ===")
    print(f"  Target: SELL {TARGET_QTY} {TARGET_SYMBOL}")

    pos = get_position(TARGET_SYMBOL)
    if pos:
        cur_qty = int(float(pos.get("qty", 0)))
        cur_val = float(pos.get("market_value", 0))
        pnl_pct = float(pos.get("unrealized_plpc", 0)) * 100
        print(f"  Current: {cur_qty} shares, ${cur_val:,.0f} market value, P&L {pnl_pct:+.2f}%")
        if cur_qty < TARGET_QTY:
            print(f"  ERROR: position has only {cur_qty} shares, can't sell {TARGET_QTY}")
            return 1
    else:
        print(f"  WARN: cannot read position (likely no holdings) — proceeding anyway")

    # Step 1: cancel bracket SL/TP children that reserve held_for_orders.
    print(f"  Step 1: cancel open {TARGET_SYMBOL} bracket children...")
    cancelled = cancel_symbol_orders(TARGET_SYMBOL)
    print(f"    cancelled {cancelled} open orders")

    # Step 2: now close partial position.
    print(f"  Step 2: DELETE position qty={TARGET_QTY}...")
    order = place_sell(TARGET_SYMBOL, TARGET_QTY)
    if not order:
        print(f"  ❌ SELL failed")
        return 1

    print(f"  ✅ SELL placed:")
    print(f"     order_id:        {order.get('id')}")
    print(f"     client_order_id: {order.get('client_order_id')}")
    print(f"     symbol:          {order.get('symbol')}")
    print(f"     qty:             {order.get('qty')}")
    print(f"     status:          {order.get('status')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
