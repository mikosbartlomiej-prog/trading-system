#!/usr/bin/env python3
"""
Close FLAT + DECAY — 2026-06-02 (exit-monitor handler: GLD/RTX CLOSE_FLAT + LINKUSD/SOLUSD CLOSE_DECAY)

Exit Monitor payload 2026-06-02T14:01:32Z flagged 4 positions for closure:

CLOSE_FLAT (intraday REVERSAL_CONFIRMED):
  - GLD   qty=23  side=long  entry=$413.95  current=$413.17  P&L=-0.19%  hold=0.2h
    Reason: intraday REVERSAL_CONFIRMED: last=413.02 below vwap=413.72 AND
    or_low=413.33; 15min slope down (rs=-1.00). Fresh position, reversal
    confirmed — exit before deeper drawdown.

  - RTX   qty=13  side=long  entry=$175.63  current=$173.29  P&L=-1.33%  hold=18.3h
    Reason: intraday REVERSAL_CONFIRMED: last=173.22 below vwap=174.08 AND
    or_low=173.36; 15min slope down (rs=-1.04). geo-defense strategy.
    18.3h hold, accelerating down. Exit.

CLOSE_DECAY (crypto past 48h threshold — hold_hours=0 bug in payload masked these):
  - LINKUSD  qty≈270  side=long  entry=$9.24  current=$8.85  P&L=-4.23%
    Estimated hold: ~63.5h (prev report 2026-06-01 18:26 UTC showed ~44h;
    now +19.5h elapsed). crypto_decay_hours=48, crypto_decay_min_pl=+5%.
    Position is -4.23% and past 48h — CLOSE_DECAY per strategy rules.

  - SOLUSD  qty≈30.07  side=long  entry=$82.97  current=$79.04  P&L=-4.74%
    Estimated hold: ~63.5h (same reasoning as LINKUSD above).
    crypto_decay_hours=48, crypto_decay_min_pl=+5%.
    Position is -4.74% and past 48h — CLOSE_DECAY per strategy rules.

Usage:
    ALPACA_API_KEY=... ALPACA_SECRET_KEY=... python3 scripts/emergency_close_20260602.py
    --dry-run: preview without placing orders
"""

import os
import sys
import json
import time
import urllib.parse
import requests
from datetime import datetime, timezone

ALPACA_BASE = "https://paper-api.alpaca.markets"

TARGETS = [
    {
        "symbol": "GLD",
        "reason": (
            "CLOSE_FLAT — intraday REVERSAL_CONFIRMED: last=413.02 below "
            "vwap=413.72 AND or_low=413.33; 15min slope down (rs=-1.00). "
            "Hold 0.2h, P&L -0.19%. Capital freed for better opportunities. "
            "Strategy: allocator."
        ),
    },
    {
        "symbol": "RTX",
        "reason": (
            "CLOSE_FLAT — intraday REVERSAL_CONFIRMED: last=173.22 below "
            "vwap=174.08 AND or_low=173.36; 15min slope down (rs=-1.04). "
            "Hold 18.3h, P&L -1.33%. Reversal accelerating. Strategy: geo-defense."
        ),
    },
    {
        "symbol": "LINKUSD",
        "reason": (
            "CLOSE_DECAY — crypto_decay_hours=48 exceeded (~63.5h estimated hold). "
            "P&L -4.23% (below crypto_decay_min_pl=+5%). hold_hours=0 bug in "
            "exit-monitor payload masked this; manually identified via prev report "
            "2026-06-01 18:26 UTC showing ~44h + 19.5h elapsed. Strategy: unknown/crypto."
        ),
    },
    {
        "symbol": "SOLUSD",
        "reason": (
            "CLOSE_DECAY — crypto_decay_hours=48 exceeded (~63.5h estimated hold). "
            "P&L -4.74% (below crypto_decay_min_pl=+5%). Same hold_hours bug. "
            "Strategy: unknown/crypto."
        ),
    },
]


def _headers() -> dict:
    key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        print("ERROR: ALPACA_API_KEY + ALPACA_SECRET_KEY required")
        sys.exit(1)
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def cancel_open_orders(symbol: str, h: dict, dry_run: bool) -> list:
    """Cancel any open bracket/GTC orders for symbol before close."""
    cancelled = []
    try:
        r = requests.get(
            f"{ALPACA_BASE}/v2/orders",
            headers=h,
            params={"status": "open", "symbols": symbol, "limit": 50},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"  [{symbol}] orders-list HTTP {r.status_code}: {r.text[:200]}")
            return cancelled
        orders = r.json()
        if not orders:
            print(f"  [{symbol}] no open orders to cancel")
            return cancelled
        for o in orders:
            oid = o.get("id", "")
            side = o.get("side", "?")
            limit_px = o.get("limit_price", "?")
            print(f"  [{symbol}] {'[DRY] ' if dry_run else ''}cancel order "
                  f"{oid} side={side} limit=${limit_px}")
            if not dry_run:
                r2 = requests.delete(
                    f"{ALPACA_BASE}/v2/orders/{oid}", headers=h, timeout=15
                )
                print(f"  [{symbol}]   cancel → HTTP {r2.status_code}")
            cancelled.append(oid)
    except Exception as e:
        print(f"  [{symbol}] cancel_open_orders exception: {e}")
    return cancelled


def close_position(symbol: str, h: dict, dry_run: bool) -> dict:
    """
    PRIMARY: DELETE /v2/positions/{symbol} — canonical close.
    Bypasses paper API buying-power gates; references existing position only.
    FALLBACK: POST /v2/orders MARKET sell — if DELETE fails.
    """
    enc = urllib.parse.quote(symbol, safe="")
    result = {"symbol": symbol, "status": "unknown", "order_id": None}

    if dry_run:
        print(f"  [{symbol}] [DRY] would DELETE /v2/positions/{enc}")
        result["status"] = "dry_run"
        return result

    # PRIMARY: DELETE
    try:
        r = requests.delete(
            f"{ALPACA_BASE}/v2/positions/{enc}",
            headers=h,
            timeout=20,
        )
        if r.status_code in (200, 207):
            body = r.json() if r.text else {}
            oid = body.get("id") or (body[0].get("id") if isinstance(body, list) else None)
            print(f"  [{symbol}] DELETE OK → order_id={oid}")
            result.update({"status": "closed_delete", "order_id": oid})
            return result
        if r.status_code == 404:
            print(f"  [{symbol}] DELETE 404 — position already closed (idempotent OK)")
            result["status"] = "already_closed"
            return result
        print(f"  [{symbol}] DELETE {r.status_code}: {r.text[:200]} — trying POST fallback")
    except Exception as e:
        print(f"  [{symbol}] DELETE exception: {e} — trying POST fallback")

    # FALLBACK: MARKET sell
    is_crypto = "/" in symbol
    side = "sell"
    try:
        # Get current qty
        rp = requests.get(f"{ALPACA_BASE}/v2/positions/{enc}", headers=h, timeout=15)
        if rp.status_code == 404:
            print(f"  [{symbol}] position 404 before MARKET fallback — skip")
            result["status"] = "already_closed"
            return result
        pos = rp.json()
        qty = abs(float(pos.get("qty", 0)))
        if qty <= 0:
            print(f"  [{symbol}] qty=0 — skip")
            result["status"] = "already_closed"
            return result

        order_payload: dict = {
            "symbol": symbol,
            "qty": str(round(qty, 9) if is_crypto else int(qty)),
            "side": side,
            "type": "market",
            "time_in_force": "gtc" if is_crypto else "day",
        }
        ro = requests.post(
            f"{ALPACA_BASE}/v2/orders",
            headers={**h, "Content-Type": "application/json"},
            data=json.dumps(order_payload),
            timeout=20,
        )
        body = ro.json() if ro.text else {}
        oid = body.get("id")
        print(f"  [{symbol}] MARKET fallback HTTP {ro.status_code} → order_id={oid}")
        result.update({"status": "closed_market_fallback", "order_id": oid,
                        "http_status": ro.status_code})
    except Exception as e:
        print(f"  [{symbol}] MARKET fallback exception: {e}")
        result["status"] = "error"

    return result


def main():
    dry_run = "--dry-run" in sys.argv
    h = _headers()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = []

    print(f"\n{'[DRY RUN] ' if dry_run else ''}=== emergency_close_20260602 @ {ts} ===")
    print(f"Targets: {[t['symbol'] for t in TARGETS]}\n")

    for target in TARGETS:
        sym = target["symbol"]
        reason = target["reason"]
        print(f"\n--- {sym} ---")
        print(f"  Reason: {reason[:120]}...")

        cancelled = cancel_open_orders(sym, h, dry_run)
        if cancelled and not dry_run:
            time.sleep(0.5)  # brief pause after cancel

        result = close_position(sym, h, dry_run)
        result["reason"] = reason
        result["cancelled_orders"] = cancelled
        results.append(result)
        time.sleep(0.3)

    print("\n=== SUMMARY ===")
    for r in results:
        print(f"  {r['symbol']}: {r['status']}  order_id={r.get('order_id')}")

    # Machine-readable result for workflow parsing
    print("\nMACHINE_READABLE_RESULT=" + json.dumps({
        "timestamp": ts,
        "dry_run": dry_run,
        "results": results,
    }))


if __name__ == "__main__":
    main()
