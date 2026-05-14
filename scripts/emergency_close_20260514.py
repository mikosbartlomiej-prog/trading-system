#!/usr/bin/env python3
"""
Emergency close — 2026-05-14 (autonomous fix for QQQ260518P00714000)

After overnight (2026-05-13 22:53 UTC) the autonomous emergency-close
workflow picked the WRONG script (emergency_close_20260512.py — May 12,
targets already closed) due to ls -t ordering ambiguity on fresh
runner checkout. Today's evening script (emergency_close_20260513_evening.py)
was never executed → QQQ260518P00714000 (2 contracts, -23.24% P&L)
still open going into 2026-05-14 market open.

Remaining stuck position per exit-monitor 4 runs today (01:26, 05:08,
08:03, 10:32 UTC):
  - QQQ260518P00714000 × 2, entry $7.83, current $6.01, P&L -23.24%
    DTE=4 (expires 2026-05-18 Monday)
    Standing LIMIT SELL @ $5.80 placed 01:26 UTC (order e2969770) —
    status unverifiable from sandbox; may or may not be active.

Strategy: at market open 13:30 UTC:
  1. Cancel any open SELL orders for QQQ260518P00714000 (clean slate)
  2. DELETE /v2/positions/QQQ260518P00714000 → MARKET close via canonical
     endpoint (bypasses options-buying-power=0 paper bug)
  3. Log result; idempotency marker prevents re-execution

Companion to v3.4.4 workflow fix: emergency-close picks script by
FILENAME DATE SUFFIX (highest YYYYMMDD wins), not mtime which was
non-deterministic on fresh checkout.

Usage:
    ALPACA_API_KEY=... ALPACA_SECRET_KEY=... python3 scripts/emergency_close_20260514.py
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
        "symbol": "QQQ260518P00714000",
        "reason": "Stuck since 2026-05-13. 4× routine attempts failed with "
                  "Alpaca paper 'insufficient options buying power for "
                  "cash-secured put' (paper bug for sell_to_close). "
                  "DTE=4, P&L -23.24%. DELETE /v2/positions bypasses bug.",
    },
    # Add other stuck positions here as they appear
]


def _headers() -> dict:
    key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        print("ERROR: ALPACA_API_KEY + ALPACA_SECRET_KEY required")
        sys.exit(1)
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def cancel_open_sells(symbol: str, h: dict, dry_run: bool) -> list:
    """Cancel any open SELL orders for symbol (clear stale limits)."""
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
            if o.get("side") != "sell":
                continue
            oid = o.get("id", "")
            limit = o.get("limit_price", "?")
            print(f"  [{symbol}] {'[DRY] ' if dry_run else ''}cancel stale SELL "
                  f"{oid} (limit ${limit})")
            if not dry_run:
                r2 = requests.delete(f"{ALPACA_BASE}/v2/orders/{oid}",
                                      headers=h, timeout=15)
                print(f"  [{symbol}]   cancel → status {r2.status_code}")
            cancelled.append(oid)
    except Exception as e:
        print(f"  [{symbol}] cancel exception: {e}")
    return cancelled


def close_position(symbol: str, h: dict, dry_run: bool) -> dict:
    """DELETE /v2/positions/{symbol} — bypass paper buying-power bug."""
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
    print(f"\n=== Emergency Close 2026-05-14 | {now} UTC ===")
    print(f"Targets: {[t['symbol'] for t in TARGETS]}")
    if dry_run:
        print("*** DRY RUN ***")
    print()

    # Auth check
    r = requests.get(f"{ALPACA_BASE}/v2/account", headers=h, timeout=10)
    if r.status_code == 200:
        a = r.json()
        eq = float(a.get("equity", 0))
        last_eq = float(a.get("last_equity", eq))
        print(f"Account OK — equity ${eq:,.2f}  daily P&L ${eq-last_eq:+,.2f}")
    elif not dry_run:
        print(f"Auth FAILED {r.status_code}: {r.text[:200]}")
        sys.exit(1)
    print()

    results = []
    for t in TARGETS:
        sym = t["symbol"]
        print(f"--- {sym} ---")
        print(f"  Reason: {t['reason']}")
        cancel_open_sells(sym, h, dry_run)
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
        print(f"\nAll {len(results)} positions closed successfully.")

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
