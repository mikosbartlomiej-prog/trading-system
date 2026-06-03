#!/usr/bin/env python3
"""
PROFIT_LOCK close — 2026-06-03 (exit-monitor handler: RED_DAY_AFTER_GREEN governor)

Exit Monitor payload 2026-06-03T14:50:41Z flagged 7 positions for PROFIT_LOCK closure.

Trigger: RED_DAY_AFTER_GREEN governor state
  peak daily P&L = +$881 (14:xx UTC)
  current daily P&L = +$283 (14:50 UTC)
  giveback = 68%  (threshold: 50% retrace from peak >= $500)
  min_profit_to_arm_usd = $500 (v3.13.3)

Per v3.5 IntradayProfitGovernor: RED_DAY_AFTER_GREEN state closes ALL intraday
non-hedge positions. All 7 positions hold_hours <= 1.1h (intraday). Emergency
closes bypass PDT guard per CLAUDE.md iron rules.

Positions to close (all LONG, all allocator strategy):
  - AMD   qty=32   entry=$525.66  current=$530.38  P&L=+0.90%  hold=1.0h
  - CRWD  qty=17   entry=$745.53  current=$751.95  P&L=+0.86%  hold=1.1h
  - GLD   qty=16   entry=$406.59  current=$408.82  P&L=+0.55%  hold=1.1h
  - NOW   qty=106  entry=$120.95  current=$121.34  P&L=+0.32%  hold=1.1h
  - ORCL  qty=55   entry=$231.06  current=$231.17  P&L=+0.05%  hold=1.1h
  - PANW  qty=45   entry=$277.74  current=$277.60  P&L=-0.05%  hold=1.1h
  - SPY   qty=12   entry=$756.44  current=$755.78  P&L=-0.09%  hold=0.0h

Total unrealized P&L to lock in: ~+$329.20
Expected daily P&L after close: ~+$612 (realized + unrealized)

Tags: exit-profit-lock-* (per v3.3 PROFIT_LOCK tagging convention)

Usage:
    ALPACA_API_KEY=... ALPACA_SECRET_KEY=... python3 scripts/emergency_close_20260603.py
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
        "symbol": "AMD",
        "qty_expected": 32,
        "reason": (
            "exit-profit-lock-AMD — RED_DAY_AFTER_GREEN governor: peak $+881 -> "
            "current $+283 (68% giveback, threshold 50%). All intraday positions "
            "closed per v3.5 IntradayProfitGovernor. Hold 1.0h, P&L +0.90%. "
            "Strategy: allocator."
        ),
    },
    {
        "symbol": "CRWD",
        "qty_expected": 17,
        "reason": (
            "exit-profit-lock-CRWD — RED_DAY_AFTER_GREEN governor: peak $+881 -> "
            "current $+283 (68% giveback, threshold 50%). All intraday positions "
            "closed per v3.5 IntradayProfitGovernor. Hold 1.1h, P&L +0.86%. "
            "Strategy: allocator."
        ),
    },
    {
        "symbol": "GLD",
        "qty_expected": 16,
        "reason": (
            "exit-profit-lock-GLD — RED_DAY_AFTER_GREEN governor: peak $+881 -> "
            "current $+283 (68% giveback, threshold 50%). All intraday positions "
            "closed per v3.5 IntradayProfitGovernor. Hold 1.1h, P&L +0.55%. "
            "Strategy: allocator."
        ),
    },
    {
        "symbol": "NOW",
        "qty_expected": 106,
        "reason": (
            "exit-profit-lock-NOW — RED_DAY_AFTER_GREEN governor: peak $+881 -> "
            "current $+283 (68% giveback, threshold 50%). All intraday positions "
            "closed per v3.5 IntradayProfitGovernor. Hold 1.1h, P&L +0.32%. "
            "Strategy: allocator."
        ),
    },
    {
        "symbol": "ORCL",
        "qty_expected": 55,
        "reason": (
            "exit-profit-lock-ORCL — RED_DAY_AFTER_GREEN governor: peak $+881 -> "
            "current $+283 (68% giveback, threshold 50%). All intraday positions "
            "closed per v3.5 IntradayProfitGovernor. Hold 1.1h, P&L +0.05%. "
            "Strategy: allocator."
        ),
    },
    {
        "symbol": "PANW",
        "qty_expected": 45,
        "reason": (
            "exit-profit-lock-PANW — RED_DAY_AFTER_GREEN governor: peak $+881 -> "
            "current $+283 (68% giveback, threshold 50%). All intraday positions "
            "closed per v3.5 IntradayProfitGovernor. Hold 1.1h, P&L -0.05%. "
            "Strategy: allocator."
        ),
    },
    {
        "symbol": "SPY",
        "qty_expected": 12,
        "reason": (
            "exit-profit-lock-SPY — RED_DAY_AFTER_GREEN governor: peak $+881 -> "
            "current $+283 (68% giveback, threshold 50%). All intraday positions "
            "closed per v3.5 IntradayProfitGovernor. Hold 0.0h, P&L -0.09%. "
            "Strategy: unknown/allocator."
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
                print(f"  [{symbol}]   cancel -> HTTP {r2.status_code}")
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
            print(f"  [{symbol}] DELETE OK -> order_id={oid}")
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
    try:
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
            "qty": str(int(qty)),
            "side": "sell",
            "type": "market",
            "time_in_force": "day",
            "client_order_id": f"exit-profit-lock-{symbol.lower()}-{int(time.time())}",
        }
        ro = requests.post(
            f"{ALPACA_BASE}/v2/orders",
            headers={**h, "Content-Type": "application/json"},
            data=json.dumps(order_payload),
            timeout=20,
        )
        body = ro.json() if ro.text else {}
        oid = body.get("id")
        print(f"  [{symbol}] MARKET fallback HTTP {ro.status_code} -> order_id={oid}")
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
    failed = 0

    print(f"\n{'[DRY RUN] ' if dry_run else ''}=== emergency_close_20260603 @ {ts} ===")
    print(f"Trigger: RED_DAY_AFTER_GREEN governor — peak $881 -> $283 (68% giveback)")
    print(f"Targets: {[t['symbol'] for t in TARGETS]}\n")

    for target in TARGETS:
        sym = target["symbol"]
        reason = target["reason"]
        print(f"\n--- {sym} ---")
        print(f"  Reason: {reason[:130]}...")

        cancelled = cancel_open_orders(sym, h, dry_run)
        if cancelled and not dry_run:
            time.sleep(0.5)

        result = close_position(sym, h, dry_run)
        result["reason"] = reason
        result["cancelled_orders"] = cancelled
        results.append(result)

        if result["status"] == "error":
            failed += 1

        time.sleep(0.3)

    print("\n=== SUMMARY ===")
    for r in results:
        print(f"  {r['symbol']}: {r['status']}  order_id={r.get('order_id')}")

    print(f"\nTotal: {len(results)} targets, {failed} errors")

    # Machine-readable result for workflow parsing (idempotency marker)
    print("\nMACHINE_READABLE_RESULT=" + json.dumps({
        "timestamp": ts,
        "dry_run": dry_run,
        "trigger": "RED_DAY_AFTER_GREEN",
        "peak_pnl_usd": 881,
        "current_pnl_usd": 283,
        "giveback_pct": 68,
        "failed": failed,
        "results": [
            {"symbol": r["symbol"], "status": r["status"], "order_id": r.get("order_id")}
            for r in results
        ],
    }))


if __name__ == "__main__":
    main()
