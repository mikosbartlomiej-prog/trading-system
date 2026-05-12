#!/usr/bin/env python3
"""
Emergency close script — 2026-05-12 23:18 UTC

Closes 4 options positions flagged CLOSE_EMERGENCY by exit-monitor.
Run with proper Alpaca credentials:

    ALPACA_API_KEY=<key> ALPACA_SECRET_KEY=<secret> python3 scripts/emergency_close_20260512.py

Or with --dry-run to preview orders without executing:

    ALPACA_API_KEY=<key> ALPACA_SECRET_KEY=<secret> python3 scripts/emergency_close_20260512.py --dry-run
"""

import os
import sys
import json
import time
import requests
from datetime import datetime, timezone

ALPACA_BASE = "https://paper-api.alpaca.markets"

EMERGENCY_CLOSES = [
    # SPY expiring 2026-05-18 — MARKET (5 DTE, spread risk)
    {"symbol": "SPY260518P00739000", "qty": 1, "order_type": "market",  "limit_price": None,  "entry": 5.80, "current": 4.74, "pl_pct": -18.28},
    {"symbol": "SPY260518P00738000", "qty": 1, "order_type": "market",  "limit_price": None,  "entry": 5.08, "current": 4.31, "pl_pct": -15.16},
    # AAPL/GOOGL expiring 2026-05-20 — LIMIT (8 DTE, use price discipline)
    {"symbol": "GOOGL260520P00385000", "qty": 2, "order_type": "limit", "limit_price": 5.20,  "entry": 7.00, "current": 5.35, "pl_pct": -23.57},
    {"symbol": "AAPL260520P00295000", "qty": 1, "order_type": "limit",  "limit_price": 3.85,  "entry": 4.65, "current": 3.90, "pl_pct": -16.13},
]


def headers():
    key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        print("ERROR: Set ALPACA_API_KEY and ALPACA_SECRET_KEY env vars")
        sys.exit(1)
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def has_existing_sell(symbol: str, h: dict) -> bool:
    """Returns True if there's already an open SELL order for this symbol."""
    r = requests.get(
        f"{ALPACA_BASE}/v2/orders",
        headers=h,
        params={"status": "open", "symbols": symbol, "limit": 10},
        timeout=15,
    )
    if r.status_code != 200:
        return False
    orders = r.json()
    return any(o.get("side") == "sell" for o in orders)


def place_sell_to_close(pos: dict, h: dict, dry_run: bool) -> bool:
    symbol = pos["symbol"]
    qty = pos["qty"]
    order_type = pos["order_type"]
    limit_price = pos["limit_price"]
    ts = datetime.now(timezone.utc).strftime("%H%M%S")
    client_id = f"exit-sl-emergency-{symbol[:20]}-{ts}"

    payload = {
        "symbol": symbol,
        "qty": str(qty),
        "side": "sell",
        "time_in_force": "day",
        "type": order_type,
        "client_order_id": client_id,
    }
    if order_type == "limit" and limit_price:
        payload["limit_price"] = str(round(limit_price, 2))

    print(f"\n{'[DRY RUN] ' if dry_run else ''}SELL_TO_CLOSE {symbol} × {qty}")
    print(f"  Entry: ${pos['entry']:.2f}  Current: ${pos['current']:.2f}  P&L: {pos['pl_pct']:+.1f}%")
    print(f"  Order type: {order_type.upper()}" + (f"  Limit: ${limit_price:.2f}" if limit_price else ""))

    if dry_run:
        print("  → Would submit above order")
        return True

    if has_existing_sell(symbol, h):
        print(f"  → SKIP: open SELL order already exists for {symbol}")
        return True

    r = requests.post(f"{ALPACA_BASE}/v2/orders", headers=h, json=payload, timeout=15)
    if r.status_code in (200, 201):
        o = r.json()
        print(f"  → ORDER PLACED: id={o.get('id','?')} status={o.get('status','?')}")
        return True
    else:
        print(f"  → ERROR {r.status_code}: {r.text[:300]}")
        return False


def main():
    dry_run = "--dry-run" in sys.argv
    h = headers()

    if dry_run:
        print("=== DRY RUN MODE — no orders will be placed ===")

    print(f"\n=== Emergency Close Script | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC ===")
    print(f"Closing {len(EMERGENCY_CLOSES)} positions flagged CLOSE_EMERGENCY on 2026-05-12\n")

    # Verify auth first
    r = requests.get(f"{ALPACA_BASE}/v2/account", headers=h, timeout=10)
    if r.status_code == 200:
        acc = r.json()
        equity = float(acc.get("equity", 0))
        print(f"Account OK — equity ${equity:,.2f}")
    else:
        print(f"Auth check failed {r.status_code}: {r.text}")
        if not dry_run:
            sys.exit(1)

    results = []
    for pos in EMERGENCY_CLOSES:
        ok = place_sell_to_close(pos, h, dry_run)
        results.append((pos["symbol"], ok))
        if not dry_run:
            time.sleep(0.5)  # avoid rate limit

    print("\n=== Summary ===")
    for sym, ok in results:
        status = "✅ OK" if ok else "❌ FAILED"
        print(f"  {sym}: {status}")

    failed = [sym for sym, ok in results if not ok]
    if failed:
        print(f"\n{len(failed)} order(s) failed — close manually via dashboard:")
        print("  https://app.alpaca.markets/paper/dashboard/overview")
        sys.exit(1)
    else:
        print("\nAll orders submitted successfully.")


if __name__ == "__main__":
    main()
