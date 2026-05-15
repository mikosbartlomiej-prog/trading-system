#!/usr/bin/env python3
"""
One-shot 2026-05-15: cancel 3 stale LIMIT entry orders from first
morning-allocator manual trigger (14:46 UTC).

Background: morning-allocator was triggered manually at 14:46 UTC after
the scheduled 13:35 cron silently skipped. With RISK_PROFILE=BALANCED
default, 3/6 orders REJECTED (AMD/SMH/NVDA at 15% > 10% cap). The 3 that
PASSED (SPY/GLD/QQQ) were placed as DAY LIMITs at the bid:

  SPY  12 @ $740.99   id=2ace4d2e-8a90-4060-acc4-f2e564f46a8c
  GLD  22 @ $417.86   id=19a43b91-4fb0-4b11-a514-cec4feaf06d7
  QQQ  11 @ $710.50   id=898a6bf2-dd92-4c38-854b-0fe7bca8b2c0

Second trigger at 14:49 UTC (with RISK_PROFILE=AGGRESSIVE_PAPER) placed
6 NEW entries on the SAME 6 symbols. Account snapshot at 14:50 shows
6 positions filled — meaning the second-trigger orders filled but the
first-trigger LIMITs are still in queue (or filled and overlapping).

This script cancels the 3 first-trigger entry orders by exact ID to
prevent duplicate position accumulation before DAY TIF expires at EOD.

Idempotent: orders already cancelled / filled / not_found → reported, OK.
"""

import json
import os
import sys

import requests

ALPACA_BASE = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/")

STALE_ORDER_IDS = [
    "2ace4d2e-8a90-4060-acc4-f2e564f46a8c",   # SPY 12 @ $740.99
    "19a43b91-4fb0-4b11-a514-cec4feaf06d7",   # GLD 22 @ $417.86
    "898a6bf2-dd92-4c38-854b-0fe7bca8b2c0",   # QQQ 11 @ $710.50
]


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
    }


def fetch_order(order_id: str) -> dict | None:
    try:
        r = requests.get(
            f"{ALPACA_BASE}/v2/orders/{order_id}",
            headers=_headers(),
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        print(f"  GET /v2/orders/{order_id}: HTTP {r.status_code} {r.text[:120]}")
        return None
    except Exception as e:
        print(f"  fetch_order({order_id}) exception: {e}")
        return None


def cancel_order(order_id: str) -> bool:
    try:
        r = requests.delete(
            f"{ALPACA_BASE}/v2/orders/{order_id}",
            headers=_headers(),
            timeout=10,
        )
        # 204 No Content = success; 422 = order in non-cancellable state
        return r.status_code in (200, 204)
    except Exception as e:
        print(f"  cancel exception: {e}")
        return False


def main() -> int:
    print(f"=== Cancel first-allocator-attempt orders (2026-05-15) ===")
    print(f"Target IDs: {len(STALE_ORDER_IDS)}")
    cancelled = 0
    already_done = 0
    not_found = 0
    failed = 0

    for oid in STALE_ORDER_IDS:
        info = fetch_order(oid)
        if info is None:
            print(f"  [{oid[:8]}] NOT FOUND")
            not_found += 1
            continue
        status = info.get("status", "?")
        sym    = info.get("symbol", "?")
        side   = info.get("side", "?")
        qty    = info.get("qty", "?")
        price  = info.get("limit_price", "?")
        print(f"  [{oid[:8]}] {sym} {side} {qty} @ ${price} — status={status}")
        if status in ("filled", "canceled", "cancelled", "expired", "replaced", "done_for_day"):
            already_done += 1
            continue
        if status in ("pending_new", "new", "accepted", "partially_filled"):
            ok = cancel_order(oid)
            if ok:
                print(f"            -> CANCELLED")
                cancelled += 1
            else:
                print(f"            -> cancel FAILED (broker rejected)")
                failed += 1
        else:
            print(f"            -> unknown state, no action")
            failed += 1

    print()
    print(f"Summary: cancelled={cancelled}, already_done={already_done}, "
          f"not_found={not_found}, failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
