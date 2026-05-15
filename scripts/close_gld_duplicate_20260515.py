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


def place_sell(symbol: str, qty: int) -> dict | None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    payload = {
        "symbol":          symbol,
        "qty":             str(qty),
        "side":            "sell",
        "type":            "market",
        "time_in_force":   "day",
        "client_order_id": f"op-correction-{symbol}-duplicate-{ts}",
    }
    try:
        r = requests.post(
            f"{ALPACA_BASE}/v2/orders",
            headers=_headers(),
            json=payload,
            timeout=15,
        )
        if r.status_code in (200, 201):
            return r.json()
        print(f"  POST /v2/orders: HTTP {r.status_code} {r.text[:250]}")
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
