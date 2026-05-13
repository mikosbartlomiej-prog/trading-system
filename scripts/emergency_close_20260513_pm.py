#!/usr/bin/env python3
"""
Emergency close script — 2026-05-13 14:27 UTC (afternoon run)

Exit-monitor routine flagged 6 positions (4 CLOSE_EMERGENCY + 2 CLOSE_FLAT)
during the active trading session. Sandbox API keys are unauthorized;
this script must be run with GitHub Secret credentials.

Usage:
    ALPACA_API_KEY=<key> ALPACA_SECRET_KEY=<secret> python3 scripts/emergency_close_20260513_pm.py
    ALPACA_API_KEY=<key> ALPACA_SECRET_KEY=<secret> python3 scripts/emergency_close_20260513_pm.py --dry-run

Trigger via GitHub Actions:
    workflow_dispatch on .github/workflows/emergency-close-positions.yml
    (set SYMBOLS env or run this script directly with real creds)
"""

import os
import sys
import json
import time
import requests
from datetime import datetime, timezone

ALPACA_BASE = "https://paper-api.alpaca.markets"

# ── Pozycje do zamknięcia (per payload 14:27 UTC) ────────────────────────────
#
# CLOSE_EMERGENCY — strata przekracza próg -12%
# Market open (14:27 UTC = 10:27 ET) → LIMIT orders z ceną ~2-3% poniżej bid
#
CLOSE_EMERGENCY = [
    {
        "symbol": "GOOGL260518P00395000",
        "qty": 1,
        "order_type": "limit",
        "limit_price": 5.00,       # current $5.15, -3% buffer dla wypełnienia
        "entry": 6.70,
        "current": 5.15,
        "pl_pct": -23.13,
        "reason": "CLOSE_EMERGENCY: strata -23.1% przekracza próg -12%. "
                  "UWAGA: ta pozycja była +39.6% o 08:12 UTC — kompletny reversal.",
    },
    {
        "symbol": "QQQ260518P00713000",
        "qty": 1,
        "order_type": "limit",
        "limit_price": 8.35,       # current $8.45
        "entry": 9.74,
        "current": 8.45,
        "pl_pct": -13.24,
        "reason": "CLOSE_EMERGENCY: strata -13.2% przekracza próg -12%. DTE=5.",
    },
    {
        "symbol": "QQQ260519P00701000",
        "qty": 1,
        "order_type": "limit",
        "limit_price": 4.25,       # current $4.36
        "entry": 5.69,
        "current": 4.36,
        "pl_pct": -23.37,
        "reason": "CLOSE_EMERGENCY: strata -23.4% przekracza próg -12%. DTE=6.",
    },
    {
        "symbol": "QQQ260519P00704000",
        "qty": 1,
        "order_type": "limit",
        "limit_price": 5.18,       # current $5.30
        "entry": 6.54,
        "current": 5.30,
        "pl_pct": -18.96,
        "reason": "CLOSE_EMERGENCY: strata -19.0% przekracza próg -12%. DTE=6.",
    },
]

# CLOSE_FLAT — pozycja płaska po długim holdzie (>40h), DTE=5 zbliża się
CLOSE_FLAT = [
    {
        "symbol": "QQQ260518P00712000",
        "qty": 1,
        "order_type": "limit",
        "limit_price": 7.80,       # current $7.92; was +18.5% at 08:12 UTC
        "entry": 7.73,
        "current": 7.92,
        "pl_pct": 2.46,
        "reason": "CLOSE_FLAT: +2.5% po 42.7h. Był +18.5% o 08:12 UTC — "
                  "retrace 86% od szczytu. DTE=5, theta przyśpiesza.",
    },
    {
        "symbol": "SPY260518P00740000",
        "qty": 2,
        "order_type": "limit",
        "limit_price": 4.92,       # current $5.02
        "entry": 4.97,
        "current": 5.02,
        "pl_pct": 1.01,
        "reason": "CLOSE_FLAT: +1.0% po 44.6h. Teza nie zadziałała. DTE=5.",
    },
]

ALL_CLOSES = CLOSE_EMERGENCY + CLOSE_FLAT


def auth_headers():
    key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        print("ERROR: Set ALPACA_API_KEY and ALPACA_SECRET_KEY env vars")
        sys.exit(1)
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def has_existing_sell(symbol: str, h: dict) -> bool:
    r = requests.get(
        f"{ALPACA_BASE}/v2/orders",
        headers=h,
        params={"status": "open", "symbols": symbol, "limit": 10},
        timeout=15,
    )
    if r.status_code != 200:
        return False
    return any(o.get("side") == "sell" for o in r.json())


def place_sell_to_close(pos: dict, h: dict, dry_run: bool) -> dict:
    symbol = pos["symbol"]
    ts = datetime.now(timezone.utc).strftime("%H%M%S")
    reason_tag = "sl" if pos["pl_pct"] < 0 else "flat"
    client_id = f"exit-{reason_tag}-emergency-{symbol[:20]}-{ts}"

    payload = {
        "symbol": symbol,
        "qty": str(pos["qty"]),
        "side": "sell",
        "time_in_force": "day",
        "type": pos["order_type"],
        "client_order_id": client_id,
    }
    if pos["order_type"] == "limit":
        payload["limit_price"] = str(round(pos["limit_price"], 2))

    label = "[DRY RUN] " if dry_run else ""
    print(f"\n{label}SELL_TO_CLOSE {symbol} × {pos['qty']}")
    print(f"  Entry: ${pos['entry']:.2f}  Current: ${pos['current']:.2f}  "
          f"P&L: {pos['pl_pct']:+.1f}%")
    print(f"  {pos['order_type'].upper()} @ ${pos['limit_price']:.2f}")
    print(f"  Reason: {pos['reason']}")

    if dry_run:
        print("  → Would submit above order")
        return {"symbol": symbol, "ok": True, "mode": "dry_run"}

    if has_existing_sell(symbol, h):
        print(f"  → SKIP: open SELL order already exists for {symbol}")
        return {"symbol": symbol, "ok": True, "mode": "dedup_skip"}

    r = requests.post(f"{ALPACA_BASE}/v2/orders", headers=h, json=payload, timeout=15)
    if r.status_code in (200, 201):
        o = r.json()
        print(f"  → ORDER PLACED id={o.get('id','?')} status={o.get('status','?')}")
        return {"symbol": symbol, "ok": True, "id": o.get("id"), "status": o.get("status")}
    else:
        print(f"  → ERROR {r.status_code}: {r.text[:400]}")
        return {"symbol": symbol, "ok": False, "error": r.text[:200]}


def main():
    dry_run = "--dry-run" in sys.argv
    h = auth_headers()

    if dry_run:
        print("=== DRY RUN MODE — no orders will be placed ===")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n=== Emergency Close (afternoon) | {now_str} UTC ===")
    print(f"Closing {len(CLOSE_EMERGENCY)} EMERGENCY + {len(CLOSE_FLAT)} FLAT positions\n")

    # Auth check
    r = requests.get(f"{ALPACA_BASE}/v2/account", headers=h, timeout=10)
    if r.status_code == 200:
        acc = r.json()
        equity = float(acc.get("equity", 0))
        daily_pl = float(acc.get("equity", 0)) - float(acc.get("last_equity", acc.get("equity", 0)))
        print(f"Account OK — equity ${equity:,.2f}  daily P&L ${daily_pl:+,.2f}")
    else:
        print(f"Auth check FAILED {r.status_code}: {r.text}")
        if not dry_run:
            sys.exit(1)

    print("\n--- CLOSE_EMERGENCY (4 positions) ---")
    results = []
    for pos in CLOSE_EMERGENCY:
        res = place_sell_to_close(pos, h, dry_run)
        results.append(res)
        if not dry_run:
            time.sleep(0.5)

    print("\n--- CLOSE_FLAT (2 positions) ---")
    for pos in CLOSE_FLAT:
        res = place_sell_to_close(pos, h, dry_run)
        results.append(res)
        if not dry_run:
            time.sleep(0.5)

    print("\n=== Summary ===")
    for res in results:
        status_icon = "✅" if res["ok"] else "❌"
        mode = res.get("mode", "")
        mode_str = f" [{mode}]" if mode else ""
        print(f"  {status_icon} {res['symbol']}{mode_str}")

    failed = [r for r in results if not r["ok"]]
    if failed:
        print(f"\n{len(failed)} order(s) FAILED — close manually via:")
        print("  https://app.alpaca.markets/paper/dashboard/overview")
        sys.exit(1)
    else:
        print(f"\nAll {len(results)} orders submitted successfully.")

    # Machine-readable result for workflow parsing
    print("\nMACHINE_READABLE_RESULT:" + json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "ok": sum(1 for r in results if r["ok"]),
        "failed": len(failed),
        "results": results,
    }))


if __name__ == "__main__":
    main()
