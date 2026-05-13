#!/usr/bin/env python3
"""
Emergency close — 2026-05-13 evening (autonomous fix)

Closes 2 positions stuck due to specific Alpaca paper API bugs:

  - QQQ260518P00712000 (qty 1, P&L -10.48% per 15:36 report):
    Has STALE LIMIT SELL @ $7.80 (from emergency_close_20260513_pm.py
    15:22 UTC) but current cena $6.92 → limit never fills.
    Solution: cancel stale order + close via DELETE /v2/positions.

  - QQQ260518P00714000 (qty 2, P&L +1.92%):
    3× sell_to_close LIMIT failed with 403 "insufficient options
    buying power for cash-secured put" (Alpaca paper bug).
    Solution: DELETE /v2/positions/{symbol} — canonical close-position
    endpoint that bypasses options buying power checks because it
    explicitly references EXISTING position (not new short put open).

Both fixes via Alpaca's DELETE /v2/positions/{symbol_or_asset_id} endpoint:
  - Closes entire position via implicit MARKET order
  - Returns 200/201/207 with resulting order JSON
  - Returns 404 if position doesn't exist (idempotent — safe re-run)
  - Bypasses buying-power-required-for-new-open checks

Usage:
    ALPACA_API_KEY=... ALPACA_SECRET_KEY=... python3 scripts/emergency_close_20260513_evening.py
    --dry-run: preview without action

Idempotency: workflow's commit-log mechanism prevents re-execution
(once exit-reports/emergency_close_20260513_evening-*.log exists,
the auto-trigger cron skips this script).
"""

import os
import sys
import json
import time
import urllib.parse
import requests
from datetime import datetime, timezone

ALPACA_BASE = "https://paper-api.alpaca.markets"

# Targets: stuck options positions per exit-monitor 15:36 UTC report.
# DELETE endpoint closes full position (no qty specified = entire qty).
TARGETS = [
    {
        "symbol": "QQQ260518P00712000",
        "reason": "STALE LIMIT SELL @ $7.80 from emergency_close_20260513_pm "
                  "(current ~$6.92, won't fill). Approaching -12% emergency "
                  "threshold (P&L -10.48% per 15:36 UTC report). DTE=5.",
    },
    {
        "symbol": "QQQ260518P00714000",
        "reason": "3× sell_to_close LIMIT failed with Alpaca 403 'insufficient "
                  "options buying power for cash-secured put' (paper bug). "
                  "P&L +1.92% per 15:36 UTC report. DTE=5; theta acceleration.",
    },
]


def _headers() -> dict:
    key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        print("ERROR: ALPACA_API_KEY and ALPACA_SECRET_KEY required")
        sys.exit(1)
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def cancel_open_sells_for(symbol: str, h: dict, dry_run: bool) -> list:
    """Cancel any open SELL orders for symbol — clears stale limits."""
    cancelled = []
    try:
        r = requests.get(
            f"{ALPACA_BASE}/v2/orders",
            headers=h,
            params={"status": "open", "symbols": symbol, "limit": 50},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"  [{symbol}] orders list failed: {r.status_code}")
            return cancelled
        for o in r.json():
            if o.get("side") != "sell":
                continue
            oid = o.get("id", "")
            limit = o.get("limit_price", "?")
            print(f"  [{symbol}] {'[DRY] ' if dry_run else ''}cancel stale SELL "
                  f"order {oid} (limit ${limit})")
            if dry_run:
                cancelled.append(oid)
                continue
            r2 = requests.delete(f"{ALPACA_BASE}/v2/orders/{oid}",
                                  headers=h, timeout=15)
            if r2.status_code in (200, 204):
                print(f"  [{symbol}]   → cancel OK ({r2.status_code})")
            else:
                print(f"  [{symbol}]   → cancel response {r2.status_code}: "
                      f"{r2.text[:200]}")
            cancelled.append(oid)
    except Exception as e:
        print(f"  [{symbol}] cancel exception: {e}")
    return cancelled


def close_position(symbol: str, h: dict, dry_run: bool) -> dict:
    """
    DELETE /v2/positions/{symbol} — canonical close-entire-position endpoint.
    Bypasses options buying-power check because it explicitly references
    an existing position rather than opening a new short put.
    """
    enc = urllib.parse.quote(symbol, safe="")
    print(f"  [{symbol}] {'[DRY] ' if dry_run else ''}DELETE /v2/positions/{symbol}")
    if dry_run:
        return {"ok": True, "mode": "dry_run", "symbol": symbol}
    try:
        r = requests.delete(f"{ALPACA_BASE}/v2/positions/{enc}",
                             headers=h, timeout=15)
        if r.status_code in (200, 201, 207):
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text[:200]}
            order_id = body.get("id") or "?"
            status = body.get("status") or "?"
            print(f"  [{symbol}]   → CLOSE OK: order_id={order_id} status={status}")
            return {"ok": True, "symbol": symbol, "order": body}
        elif r.status_code == 404:
            print(f"  [{symbol}]   → 404 position not found (already closed)")
            return {"ok": True, "mode": "already_closed", "symbol": symbol}
        else:
            print(f"  [{symbol}]   → CLOSE ERROR {r.status_code}: {r.text[:400]}")
            return {"ok": False, "symbol": symbol, "error": r.text[:300],
                     "status_code": r.status_code}
    except Exception as e:
        print(f"  [{symbol}]   → CLOSE EXCEPTION: {e}")
        return {"ok": False, "symbol": symbol, "error": str(e)}


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    h = _headers()
    if dry_run:
        print("=== DRY RUN MODE — no API mutations ===")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n=== Emergency Close (evening) | {now_str} UTC ===")
    print(f"Targets: {[t['symbol'] for t in TARGETS]}\n")

    # Auth check
    r = requests.get(f"{ALPACA_BASE}/v2/account", headers=h, timeout=10)
    if r.status_code == 200:
        a = r.json()
        eq = float(a.get("equity", 0))
        last_eq = float(a.get("last_equity", eq))
        daily_pl = eq - last_eq
        print(f"Account OK — equity ${eq:,.2f}  daily P&L ${daily_pl:+,.2f}")
    else:
        print(f"Auth check FAILED {r.status_code}: {r.text[:300]}")
        if not dry_run:
            sys.exit(1)
    print()

    results = []
    for t in TARGETS:
        sym = t["symbol"]
        print(f"--- {sym} ---")
        print(f"  Reason: {t['reason']}")
        # Step 1: cancel any stale SELL orders for this symbol
        cancel_open_sells_for(sym, h, dry_run)
        if not dry_run:
            time.sleep(0.5)
        # Step 2: close position via DELETE
        res = close_position(sym, h, dry_run)
        results.append(res)
        print()
        if not dry_run:
            time.sleep(0.5)

    print("=== Summary ===")
    for r in results:
        icon = "✅" if r.get("ok") else "❌"
        mode = r.get("mode", "")
        mode_str = f" [{mode}]" if mode else ""
        print(f"  {icon} {r['symbol']}{mode_str}")

    failed = [r for r in results if not r.get("ok")]
    if failed:
        print(f"\n{len(failed)} target(s) FAILED — manual fallback:")
        print("  https://app.alpaca.markets/paper/dashboard/overview")
    else:
        print(f"\nAll {len(results)} positions closed successfully.")

    # Machine-readable result for workflow log parsing
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
