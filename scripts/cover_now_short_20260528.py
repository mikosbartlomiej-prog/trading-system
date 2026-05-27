#!/usr/bin/env python3
"""scripts/cover_now_short_20260528.py — one-shot buy-to-cover for NOW SHORT.

Background: 2026-05-27 stale allocator EXIT MARKET created -169 NOW naked
short (~$16k). Operator tried manual buy-to-cover at 20:32 UTC but Alpaca
canceled the order (market closed since 20:00 UTC, no extended_hours flag).

This script runs ONCE at 13:31 UTC on 2026-05-28 (1 min after market open)
to cover the position via the v3.10 safe_close infrastructure.

Behavior:
- Check live NOW position; if not present or side != short → exit 0 (no-op)
- If short → safe_close(symbol="NOW", intent_side="buy", reason_tag="op-correction-now-cover-20260528")
  - safe_close auto-detects intent=buy + live=short → buy-to-cover allowed
  - MARKET order via Alpaca paper → instant fill at market open
- Audit JSONL automatically emitted by safe_close
- Email summary via send_email

Exit codes:
  0 — success or no-op (position already covered)
  1 — fatal (creds missing or unexpected error)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "shared"))


def main() -> int:
    print(f"=== cover_now_short_20260528 @ {datetime.now(timezone.utc).isoformat()} ===")

    if not os.environ.get("ALPACA_API_KEY"):
        print("FATAL: ALPACA_API_KEY missing")
        return 1

    try:
        from alpaca_orders import safe_close, _fetch_single_position
    except ImportError as e:
        print(f"FATAL: import error: {e}")
        return 1

    pos = _fetch_single_position("NOW")
    if not pos:
        print("NOW position not found (404) — already covered. Exit 0 (no-op).")
        return 0

    side = (pos.get("side") or "").lower()
    qty = abs(float(pos.get("qty") or 0))
    mv = abs(float(pos.get("market_value") or 0))

    print(f"NOW live: side={side} qty={qty} market_value=${mv:,.2f}")

    if side != "short":
        print(f"NOW is LONG (qty={qty}), not SHORT. Nothing to cover. Exit 0.")
        return 0

    if qty <= 0:
        print("NOW qty=0 — nothing to cover. Exit 0.")
        return 0

    print(f"Initiating buy-to-cover for {qty} NOW shares via safe_close...")
    result = safe_close(
        symbol="NOW",
        intent_qty=qty,
        intent_side="buy",  # buy-to-cover short position
        reason_tag="op-correction-now-cover-20260528",
        order_type="market",
        time_in_force="day",
        is_crypto=False,
        allow_market=True,
    )

    print(f"safe_close result: status={result['status']} reason={result['reason']}")
    if result.get("alpaca_order_id"):
        print(f"  alpaca_order_id: {result['alpaca_order_id']}")
    if result.get("actual_qty") is not None:
        print(f"  actual_qty: {result['actual_qty']}")

    # Email summary
    try:
        from notify import send_email
        subject = f"[op-correction] NOW SHORT cover — {result['status']}"
        body = (
            f"One-shot buy-to-cover for NOW SHORT position.\n"
            f"\n"
            f"Trigger:      scheduled workflow 2026-05-28 13:31 UTC (after Tuesday's stale-plan incident)\n"
            f"Live qty:     {qty} (short)\n"
            f"Live mv:      ${mv:,.2f}\n"
            f"Status:       {result['status']}\n"
            f"Reason:       {result['reason']}\n"
            f"Order id:     {result.get('alpaca_order_id', 'n/a')}\n"
            f"\n"
            f"Background: 2026-05-27 14:00 UTC allocator sent EXIT MARKET 169\n"
            f"on a NOW position already closed by overnight bracket SL → Alpaca\n"
            f"paper accepted naked short -169. v3.10 safe_close ships invariant\n"
            f"that prevents this class going forward (lint test + position pre-check).\n"
            f"\n"
            f"Audit JSONL event already written by safe_close to journal/autonomy/.\n"
        )
        send_email(subject=subject, body=body)
        print(f"Email sent: {subject}")
    except Exception as e:
        print(f"(non-fatal) email send failed: {e}")

    # Non-zero exit only on hard failure; skipped/placed both = success
    if result["status"] in ("placed", "skipped"):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
