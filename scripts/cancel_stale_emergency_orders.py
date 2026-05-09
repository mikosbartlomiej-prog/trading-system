"""
One-shot cleanup: cancel stale exit-emergency LIMIT orders in Alpaca.

Background: before the 2026-05-09 MARKET-order patch (commits c4bc437 +
0f7ce0b), exit-emergency orders were placed by the Exit Handler routine
as LIMIT orders. In fast-market conditions LIMITs don't fill, so 4
stale `exit-emergency-*` orders accumulated in Alpaca with status=open,
giving phantom emergency-exit protection that would never execute.

This script: lists open orders → filters those whose client_order_id
starts with `exit-emergency` AND type=='limit' AND status in
{accepted, new, partially_filled, pending_new} → DELETE /v2/orders/{id}
each → prints summary. Idempotent — re-running after all stale orders
are gone is a safe no-op.

Run via GitHub workflow (scripts/cancel-stale-emergency-orders.yml) so
secrets stay in CI and never touch local filesystem. Output goes to
workflow log.
"""

import json
import os
import sys

import requests


ALPACA_BASE_URL = "https://paper-api.alpaca.markets"
STALE_PREFIX     = "exit-emergency"   # client_order_id prefix to target
STALE_TYPES      = {"limit"}           # only LIMIT (new emergency uses market)
OPEN_STATUSES    = {"new", "accepted", "partially_filled", "pending_new"}


def _hdr() -> dict:
    return {
        "APCA-API-KEY-ID":     os.environ.get("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.environ.get("ALPACA_SECRET_KEY", ""),
    }


def list_open_orders() -> list[dict]:
    """Return all currently-open orders (paginated)."""
    out: list[dict] = []
    params = {"status": "open", "limit": 500, "direction": "desc"}
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/v2/orders",
                         headers=_hdr(), params=params, timeout=20)
        if r.status_code != 200:
            print(f"  list orders error: HTTP {r.status_code}: {r.text[:200]}")
            return []
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"  list orders exception: {e}")
        return out


def cancel_order(order_id: str) -> tuple[bool, str]:
    """DELETE /v2/orders/{id}. Returns (success, message)."""
    try:
        r = requests.delete(f"{ALPACA_BASE_URL}/v2/orders/{order_id}",
                            headers=_hdr(), timeout=15)
        if r.status_code in (200, 204, 207):
            return True, f"HTTP {r.status_code}"
        return False, f"HTTP {r.status_code}: {r.text[:150]}"
    except Exception as e:
        return False, f"exception: {e}"


def main() -> int:
    if not _hdr()["APCA-API-KEY-ID"]:
        print("ERROR: ALPACA_API_KEY not set")
        return 1

    print("=" * 60)
    print(f"Stale exit-emergency LIMIT orders cleanup")
    print(f"  prefix:   '{STALE_PREFIX}'")
    print(f"  type:     {STALE_TYPES}")
    print(f"  statuses: {OPEN_STATUSES}")
    print("=" * 60)

    orders = list_open_orders()
    print(f"\nTotal open orders: {len(orders)}")

    candidates = []
    for o in orders:
        cid    = (o.get("client_order_id") or "").lower()
        otype  = (o.get("type")            or "").lower()
        status = (o.get("status")          or "").lower()
        if cid.startswith(STALE_PREFIX) and otype in STALE_TYPES and status in OPEN_STATUSES:
            candidates.append(o)

    if not candidates:
        print("\n✓ No stale exit-emergency LIMIT orders found.")
        print("  (Either nothing to clean up, or earlier run already handled them.)")
        return 0

    print(f"\nCandidates to cancel ({len(candidates)}):")
    for o in candidates:
        print(f"  {o.get('id')[:8]}.. | {o.get('symbol'):20s} | "
              f"side={o.get('side'):4s} | type={o.get('type'):6s} | "
              f"qty={o.get('qty'):3s} | limit={o.get('limit_price'):>8s} | "
              f"cid={o.get('client_order_id')}")

    print(f"\nCancelling ...")
    cancelled = 0
    failed = 0
    for o in candidates:
        ok, msg = cancel_order(o.get("id", ""))
        prefix = "✓" if ok else "✗"
        print(f"  {prefix} {o.get('id')[:8]}.. {o.get('symbol'):20s} → {msg}")
        if ok:
            cancelled += 1
        else:
            failed += 1

    print()
    print("=" * 60)
    print(f"Result: {cancelled} cancelled, {failed} failed (of {len(candidates)} candidates)")
    print("=" * 60)

    # Snapshot for the agent to parse
    print()
    print("MACHINE_READABLE_RESULT:")
    print(json.dumps({
        "open_orders_total": len(orders),
        "candidates_found":  len(candidates),
        "cancelled":         cancelled,
        "failed":            failed,
        "candidates":        [
            {"id": o.get("id"), "symbol": o.get("symbol"),
             "client_order_id": o.get("client_order_id"),
             "limit_price": o.get("limit_price")}
            for o in candidates
        ],
    }))

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
