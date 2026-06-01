#!/usr/bin/env python3
"""
Close FLAT — 2026-06-01 (exit-monitor CLOSE_FLAT: LMT intraday reversal)

Exit Monitor payload 2026-06-01T17:51:02Z flagged LMT for CLOSE_FLAT:
  - Symbol: LMT  qty: 4  side: long
  - Entry: $520.57  current: $520.98  P&L: +$1.64 (+0.08%)
  - Hold: 1.8h
  - Reason: intraday REVERSAL_CONFIRMED: last=521.12 below vwap=522.31
    AND or_low=521.30; 15min slope down (rs=-2.50)

Decision: position is essentially flat (+0.08%) with confirmed intraday
reversal. Capital better deployed elsewhere. Exit via DELETE /v2/positions
(canonical close, no buying-power gate issues).

Usage:
    ALPACA_API_KEY=... ALPACA_SECRET_KEY=... python3 scripts/emergency_close_20260601.py
    --dry-run: preview without action
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
        "symbol": "LMT",
        "reason": "CLOSE_FLAT — intraday REVERSAL_CONFIRMED: last=521.12 below "
                  "vwap=522.31 AND or_low=521.30; 15min slope down (rs=-2.50). "
                  "Hold 1.8h, P&L +0.08% (essentially flat). Capital freed for "
                  "better opportunities. Strategy: geo-defense.",
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
    """Cancel any open orders for symbol before close."""
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
        for o in r.json():
            oid = o.get("id", "")
            side = o.get("side", "?")
            limit = o.get("limit_price", "?")
            print(f"  [{symbol}] {'[DRY] ' if dry_run else ''}cancel order "
                  f"{oid} side={side} limit=${limit}")
            if not dry_run:
                r2 = requests.delete(f"{ALPACA_BASE}/v2/orders/{oid}",
                                      headers=h, timeout=15)
                print(f"  [{symbol}]   cancel → status {r2.status_code}")
            cancelled.append(oid)
    except Exception as e:
        print(f"  [{symbol}] cancel exception: {e}")
    return cancelled


def close_position(symbol: str, h: dict, dry_run: bool) -> dict:
    """DELETE /v2/positions/{symbol} — canonical close endpoint."""
    enc = urllib.parse.quote(symbol, safe="")
    print(f"  [{symbol}] {'[DRY] ' if dry_run else ''}DELETE /v2/positions/{symbol}")
    if dry_run:
        return {"ok": True, "mode": "dry_run", "symbol": symbol}
    try:
        r = requests.delete(f"{ALPACA_BASE}/v2/positions/{enc}",
                             headers=h, timeout=15)
        if r.status_code in (200, 201, 207):
            body = r.json()
            print(f"  [{symbol}]   → CLOSE OK: order_id={body.get('id','?')} "
                  f"status={body.get('status','?')}")
            return {"ok": True, "symbol": symbol, "order": body}
        if r.status_code == 404:
            print(f"  [{symbol}]   → 404 already closed (idempotent OK)")
            return {"ok": True, "mode": "already_closed", "symbol": symbol}
        print(f"  [{symbol}]   → ERR {r.status_code}: {r.text[:300]}")
        return {"ok": False, "symbol": symbol, "error": r.text[:200],
                "status_code": r.status_code}
    except Exception as e:
        print(f"  [{symbol}]   → EXC: {e}")
        return {"ok": False, "symbol": symbol, "error": str(e)}


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    h = _headers()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n=== Close FLAT 2026-06-01 | {now} UTC ===")
    print(f"Targets: {[t['symbol'] for t in TARGETS]}")
    if dry_run:
        print("*** DRY RUN ***")
    print()

    r = requests.get(f"{ALPACA_BASE}/v2/account", headers=h, timeout=10)
    if r.status_code == 200:
        a = r.json()
        eq = float(a.get("equity", 0))
        last_eq = float(a.get("last_equity", eq))
        print(f"Account OK — equity ${eq:,.2f}  daily P&L ${eq - last_eq:+,.2f}")
    elif not dry_run:
        print(f"Auth FAILED {r.status_code}: {r.text[:200]}")
        sys.exit(1)
    print()

    results = []
    for t in TARGETS:
        sym = t["symbol"]
        print(f"--- {sym} ---")
        print(f"  Reason: {t['reason']}")
        cancel_open_orders(sym, h, dry_run)
        if not dry_run:
            time.sleep(0.5)
        res = close_position(sym, h, dry_run)
        results.append(res)
        if not dry_run:
            time.sleep(0.5)
        print()

    failed = [r for r in results if not r.get("ok")]
    print("=== Summary ===")
    for r in results:
        icon = "✅" if r.get("ok") else "❌"
        mode = f" [{r['mode']}]" if r.get("mode") else ""
        print(f"  {icon} {r['symbol']}{mode}")

    if failed:
        print(f"\n{len(failed)} target(s) FAILED — check Alpaca dashboard manually")
    else:
        print(f"\nAll {len(results)} position(s) closed successfully.")

    print("\nMACHINE_READABLE_RESULT:" + json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "ok": sum(1 for r in results if r.get("ok")),
        "failed": len(failed),
        "results": results,
    }))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
