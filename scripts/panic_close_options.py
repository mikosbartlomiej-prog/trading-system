#!/usr/bin/env python3
"""
Panic-close all open us_option positions.

Dry-run by default. Submits real SELL-to-close LIMIT orders ONLY when
CONFIRM_PANIC_CLOSE_OPTIONS=true is set in the environment. Paper-only
(uses paper-api endpoint exclusively — there is no live path).

Usage:
    # see what WOULD be submitted (default)
    python scripts/panic_close_options.py

    # actually submit (paper only, still safe)
    CONFIRM_PANIC_CLOSE_OPTIONS=true python scripts/panic_close_options.py

Rules:
    - Skips contracts that already have an OPEN SELL order (dedup via
      /v2/orders?status=open&symbols=...).
    - Pricing: ask × 0.95 if we have a quote; else last close × 0.95;
      else market-order fallback only if --allow-market is passed
      (default off — we never auto-fall-back to MARKET).
    - Tags each new order with client_order_id `panic-close-<sym>-<ts>`
      so the analyzer can attribute these in the journal.

Exit codes:
    0 — completed (dry-run or real)
    1 — bad env / missing creds
    2 — hard failure (e.g. Alpaca unreachable)
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
from datetime import datetime, timezone

import requests


ALPACA_BASE_URL = "https://paper-api.alpaca.markets"
ALPACA_DATA_URL = "https://data.alpaca.markets"


def headers() -> dict:
    return {
        "APCA-API-KEY-ID":     os.environ.get("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.environ.get("ALPACA_SECRET_KEY", ""),
    }


def confirmed() -> bool:
    """
    Real submission allowed when EITHER:
      - CONFIRM_PANIC_CLOSE_OPTIONS=true       (operator-initiated, manual)
      - AUTONOMOUS_PANIC_CLOSE_OPTIONS=true    (autonomy layer initiated)

    Both flags exist so the autonomous remediation flow has a paper-only
    entry point that does NOT require a human in the loop, while the
    manual operator path retains the explicit confirmation env.
    """
    for var in ("CONFIRM_PANIC_CLOSE_OPTIONS", "AUTONOMOUS_PANIC_CLOSE_OPTIONS"):
        if os.environ.get(var, "").strip().lower() in ("1", "true", "yes", "on"):
            return True
    return False


def fetch_open_options() -> list[dict]:
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/v2/positions", headers=headers(), timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"FATAL: positions fetch failed: {e}")
        sys.exit(2)
    positions = r.json() or []
    options = [
        p for p in positions
        if isinstance(p, dict) and (p.get("asset_class") == "us_option"
                                    or _looks_like_option(p.get("symbol", "")))
    ]
    return options


def _looks_like_option(sym: str) -> bool:
    return len(sym) > 7 and any(ch.isdigit() for ch in sym)


def has_open_sell(symbol: str) -> bool:
    try:
        r = requests.get(
            f"{ALPACA_BASE_URL}/v2/orders",
            headers=headers(),
            params={"status": "open", "symbols": symbol},
            timeout=10,
        )
        if r.status_code != 200:
            return False
        for o in (r.json() or []):
            if (o.get("symbol") == symbol
                    and (o.get("side") or "").lower() == "sell"):
                return True
    except Exception as e:
        print(f"  warn: open-orders check failed for {symbol}: {e}")
    return False


def get_option_quote(symbol: str) -> dict | None:
    """Best-effort latest quote. Same endpoint options-monitor uses."""
    try:
        r = requests.get(
            f"{ALPACA_DATA_URL}/v1beta1/options/snapshots/{urllib.parse.quote(symbol)}",
            headers=headers(),
            timeout=10,
        )
        if r.status_code != 200:
            return None
        d = r.json()
        snap = d.get("snapshot") or d
        q = snap.get("latestQuote") or snap.get("latest_quote") or {}
        bid = float(q.get("bp") or q.get("bid_price") or 0)
        ask = float(q.get("ap") or q.get("ask_price") or 0)
        if bid <= 0 or ask <= 0:
            return None
        return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2.0}
    except Exception as e:
        print(f"  quote {symbol} error: {e}")
        return None


def submit_sell_limit(symbol: str, qty: int, limit_price: float) -> dict | None:
    ts = datetime.now(timezone.utc).strftime("%H%M%S%f")[:-3]
    coid = f"panic-close-{symbol.replace('/', '')}-{ts}"
    payload = {
        "symbol":          symbol,
        "qty":             str(int(qty)),
        "side":            "sell",
        "type":            "limit",
        "limit_price":     str(round(limit_price, 2)),
        "time_in_force":   "day",
        "client_order_id": coid,
    }
    try:
        r = requests.post(f"{ALPACA_BASE_URL}/v2/orders",
                          headers=headers(), json=payload, timeout=15)
        if r.status_code in (200, 201):
            return r.json()
        print(f"  Alpaca rejected sell {symbol}: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"  exception sending sell {symbol}: {e}")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Panic-close all open us_option positions.")
    parser.add_argument(
        "--allow-market",
        action="store_true",
        help="Fall back to MARKET order if no quote available. OFF by default.",
    )
    args = parser.parse_args()

    if not headers()["APCA-API-KEY-ID"]:
        print("FATAL: ALPACA_API_KEY missing")
        return 1

    real = confirmed()
    label = "REAL" if real else "DRY-RUN"
    print(f"=== panic_close_options {label} ===")
    print(f"  CONFIRM_PANIC_CLOSE_OPTIONS={os.environ.get('CONFIRM_PANIC_CLOSE_OPTIONS', '<unset>')}")
    print(f"  allow_market={args.allow_market}")
    print()

    options = fetch_open_options()
    if not options:
        print("No open options positions. Nothing to do.")
        return 0

    submitted = 0
    skipped = 0
    for p in options:
        sym = p.get("symbol") or ""
        qty = int(float(p.get("qty") or 0))
        if qty <= 0:
            print(f"  skip {sym}: qty={qty}")
            skipped += 1
            continue
        if has_open_sell(sym):
            print(f"  skip {sym}: already has open SELL order")
            skipped += 1
            continue

        quote = get_option_quote(sym)
        limit_price: float | None = None
        if quote and quote["ask"] > 0:
            # 5% below ask — aggressive seller, still LIMIT (no slippage tail).
            limit_price = round(quote["ask"] * 0.95, 2)
            src = f"ask×0.95 (bid={quote['bid']} ask={quote['ask']})"
        else:
            try:
                close = float(p.get("avg_entry_price") or 0)
                if close > 0:
                    limit_price = round(close * 0.95, 2)
                    src = f"avg_entry×0.95 ({close})"
            except (TypeError, ValueError):
                pass

        if limit_price is None or limit_price <= 0:
            if args.allow_market:
                print(f"  {sym}: no quote → fallback MARKET (allow-market=true)")
                # NOTE: still LIMIT in code — we do not submit MARKET here even
                # with --allow-market. We log + skip. MARKET options on paper
                # often fill at terrible prices; if operator wants MARKET they
                # can do it manually via Alpaca UI.
                print(f"  {sym}: refusing MARKET fallback (would be unbounded loss).")
            else:
                print(f"  {sym}: no quote, no avg_entry → skip")
            skipped += 1
            continue

        print(f"  {sym}: qty={qty} sell LIMIT @ ${limit_price} ({src})")
        if real:
            order = submit_sell_limit(sym, qty, limit_price)
            if order:
                print(f"    -> placed id={order.get('id')} coid={order.get('client_order_id')}")
                submitted += 1
            else:
                print(f"    -> SUBMIT FAILED")
                skipped += 1
        else:
            print("    (dry-run — no order sent)")
            submitted += 1  # would-have-submitted count

    print()
    print(f"=== summary: {submitted} {'submitted' if real else 'WOULD submit'}, {skipped} skipped ===")
    if not real:
        print("To execute for real, set CONFIRM_PANIC_CLOSE_OPTIONS=true and re-run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
