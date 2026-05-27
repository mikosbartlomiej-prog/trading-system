#!/usr/bin/env python3
"""scripts/forensic_position_origin.py — provenance audit for positions.

USE CASE:
On 2026-05-27, positions LMT + RTX appeared between 17:22 and 19:07 UTC
WITHOUT any workflow logging a trade-place action. Defense-monitor,
twitter-monitor, politician-monitor, reddit-monitor, geo-monitor all
reported zero placed orders. Origin was UNKNOWN.

This script:
1. Queries Alpaca for filled orders in a time window for specific symbols
2. Reports client_order_id (which encodes strategy/intent prefix)
3. Reports submitted_at vs filled_at timestamps
4. Cross-references with parent_order_id to detect bracket child fills
   (carry-over from prior sessions)
5. Emits JSONL audit event for each finding (so future forensics have data)

USAGE:
  python3 scripts/forensic_position_origin.py --symbols LMT,RTX \\
      --after 2026-05-27T00:00:00Z --before 2026-05-27T20:00:00Z

REQUIRES:
  ALPACA_API_KEY, ALPACA_SECRET_KEY env vars (no fallback — fail loudly)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "shared"))

import requests  # noqa: E402

ALPACA_BASE = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")


def headers() -> dict:
    return {
        "APCA-API-KEY-ID":     os.environ.get("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.environ.get("ALPACA_SECRET_KEY", ""),
    }


# Known client_order_id prefixes (from grep across repo):
KNOWN_PREFIXES = {
    "stock-":             "shared.alpaca_orders.execute_stock_signal (entry)",
    "crypto-":            "shared.alpaca_orders.execute_crypto_signal (entry)",
    "options-momentum-":  "options-monitor/monitor.py (BUY_TO_OPEN)",
    "alloc-exit-":        "shared.allocator._exec_exit (allocator EXIT)",
    "alloc-reduce-":      "shared.allocator._exec_reduce (allocator REDUCE)",
    "allocator-rebalance-": "shared.allocator._exec_buy (allocator BUY)",
    "exit-emergency-":    "exit-monitor.place_emergency_close (SL/CLOSE)",
    "exit-tp-":           "options-exit-monitor (TP fill)",
    "exit-sl-":           "options-exit-monitor (SL fill)",
    "exit-trail-":        "options-exit-monitor TRAIL",
    "exit-regime-":       "options-exit-monitor REGIME",
    "exit-governor-":     "options-exit-monitor GOVERNOR (intraday)",
    "exit-profit-lock-":  "exit-monitor PROFIT_LOCK cascade",
    "recreate-exit-":     "shared.remediation._do_recreate_exit_plan (v3.9.6)",
    "panic-close-":       "scripts/panic_close_options.py",
    "op-correction-":     "operator manual correction",
    "operational-correction-": "operator manual correction (alt prefix)",
}


def fetch_filled_orders(symbols: list[str], after: str, before: str) -> list[dict]:
    """GET /v2/orders?status=closed (filled+cancelled+expired) with filters."""
    q = {
        "status":  "closed",
        "symbols": ",".join(symbols),
        "after":   after,
        "until":   before,
        "limit":   500,
        "direction": "asc",
    }
    url = f"{ALPACA_BASE}/v2/orders?{urlencode(q)}"
    r = requests.get(url, headers=headers(), timeout=30)
    if r.status_code != 200:
        print(f"FATAL: Alpaca orders fetch failed: {r.status_code} {r.text[:300]}")
        sys.exit(1)
    return r.json() or []


def classify_prefix(client_order_id: str | None) -> tuple[str, str]:
    """Returns (origin_label, classification) — UNKNOWN if no known prefix."""
    if not client_order_id:
        return ("MISSING_COID", "Order has no client_order_id (UUID-only) — direct Alpaca dashboard or external")
    for prefix, label in KNOWN_PREFIXES.items():
        if client_order_id.startswith(prefix):
            return (label, "KNOWN")
    return (f"UNKNOWN_PREFIX:{client_order_id[:40]}", "UNKNOWN")


def main() -> int:
    p = argparse.ArgumentParser(description="Forensic position origin audit")
    p.add_argument("--symbols", required=True, help="Comma-separated tickers e.g. LMT,RTX")
    p.add_argument("--after",   default=(datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    p.add_argument("--before",  default=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    p.add_argument("--emit-audit", action="store_true",
                   help="Write findings to journal/autonomy/<date>.jsonl")
    args = p.parse_args()

    if not headers()["APCA-API-KEY-ID"]:
        print("FATAL: ALPACA_API_KEY missing")
        return 1

    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    print(f"=== FORENSIC POSITION ORIGIN ===")
    print(f"Symbols: {symbols}")
    print(f"Window:  {args.after} → {args.before}")
    print()

    orders = fetch_filled_orders(symbols, args.after, args.before)
    print(f"Found {len(orders)} closed order(s) in window")
    print()

    findings: list[dict] = []
    unknown_count = 0
    for o in orders:
        sym = o.get("symbol", "?")
        side = o.get("side", "?")
        qty = o.get("filled_qty", "?")
        coid = o.get("client_order_id")
        oid = o.get("id", "?")
        parent_oid = o.get("parent_order_id")
        status = o.get("status", "?")
        sub_at = o.get("submitted_at", "")[:19]
        fil_at = o.get("filled_at", "")[:19] if o.get("filled_at") else ""

        origin, klass = classify_prefix(coid)
        if klass == "UNKNOWN" or klass == "MISSING_COID":
            unknown_count += 1
            marker = "❌ UNKNOWN"
        else:
            marker = "✅ KNOWN  "

        parent_info = f" parent={parent_oid[:8]}" if parent_oid else ""

        print(f"{marker} | {sub_at} | {sym:<6} {side:<4} qty={qty:>4} status={status:<10}{parent_info}")
        print(f"           coid: {coid or '<missing>'}")
        print(f"           origin: {origin}")
        if fil_at and fil_at != sub_at:
            print(f"           filled_at: {fil_at}")
        print()

        findings.append({
            "symbol":            sym,
            "side":              side,
            "filled_qty":        qty,
            "client_order_id":   coid,
            "alpaca_order_id":   oid,
            "parent_order_id":   parent_oid,
            "status":            status,
            "submitted_at":      sub_at,
            "filled_at":         fil_at,
            "origin_label":      origin,
            "classification":    klass,
        })

    print(f"=== SUMMARY ===")
    print(f"Total orders: {len(orders)}")
    print(f"Unknown origin: {unknown_count}")
    if unknown_count > 0:
        print(f"⚠️  {unknown_count} order(s) with UNKNOWN client_order_id prefix.")
        print("   Possible sources: routine path execution, manual Alpaca dashboard,")
        print("   external session, or bracket child fill (parent_order_id != null).")

    if args.emit_audit:
        try:
            from autonomy import make_decision
            from audit import write_audit_event
            d = make_decision(
                decision_type="CLEANUP_STALE_ORDERS",  # closest enum for forensic
                decision="REPORTED" if unknown_count == 0 else "INVESTIGATE",
                reason=f"forensic audit symbols={symbols} window={args.after}..{args.before}",
                actor="forensic_position_origin",
                affected_symbols=symbols,
                inputs={"orders": len(orders), "unknown": unknown_count},
                risk_metrics={"unknown_origin_count": unknown_count},
                action_taken="provenance_audit",
                result="reported",
                reversible=True,
            )
            write_audit_event(d, kind="trading")
            print(f"Audit JSONL emitted.")
        except Exception as e:
            print(f"Audit emission failed (non-fatal): {e}")

    return 0 if unknown_count == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
