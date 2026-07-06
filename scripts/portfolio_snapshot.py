"""
Portfolio snapshot via Alpaca REST.

Usage (locally):
    ALPACA_API_KEY=$KEY ALPACA_SECRET_KEY=$SECRET python scripts/portfolio_snapshot.py

Usage (CI):
    Triggered manually via .github/workflows/snapshot.yml — output goes
    to the run log. Operator (or Claude in a session) reads the log and
    pastes back into chat for analysis.

Output: a single-line JSON identical in shape to the dashboard worker's
/api/snapshot response — same keys (account, positions, orders, errors,
timestamp) — so existing analyzers parse it without changes.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import requests


ALPACA_BASE_URL = "https://paper-api.alpaca.markets"
ALPACA_DATA_URL = "https://data.alpaca.markets"

# Read-only quote symbols for the morning-routine playbook (VIXY as VIX proxy
# per playbooks/morning-routine.md step 2, plus SPY/QQQ per step 3).
QUOTE_SYMBOLS = ["SPY", "QQQ", "VIXY"]


def _hdr() -> dict:
    return {
        "APCA-API-KEY-ID":     os.environ.get("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.environ.get("ALPACA_SECRET_KEY", ""),
    }


def _get(path: str, params: dict | None = None, base: str = ALPACA_BASE_URL) -> tuple[object, str | None]:
    try:
        r = requests.get(f"{base}{path}",
                         headers=_hdr(), params=params or {}, timeout=15)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {r.text[:200]}"
        return r.json(), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def main() -> int:
    if not _hdr()["APCA-API-KEY-ID"]:
        print(json.dumps({"error": "ALPACA_API_KEY not set"}))
        return 1

    errors: list[str] = []

    # Account
    account, err = _get("/v2/account")
    if err:
        errors.append(f"account: {err}")
        account = {}

    eq      = float(account.get("equity") or 0) if account else 0
    last_eq = float(account.get("last_equity") or eq) if account else 0
    daily_pl     = eq - last_eq if last_eq else 0
    daily_pl_pct = (daily_pl / last_eq * 100) if last_eq else 0
    account_norm = {
        "equity":       eq,
        "last_equity":  last_eq,
        "cash":         float(account.get("cash") or 0) if account else 0,
        "buying_power": float(account.get("buying_power") or 0) if account else 0,
        "daily_pl":     round(daily_pl, 2),
        "daily_pl_pct": round(daily_pl_pct, 4),
        "account_id":   account.get("account_number") or account.get("id") if account else None,
    }

    # Positions
    positions_raw, err = _get("/v2/positions")
    if err:
        errors.append(f"positions: {err}")
        positions_raw = []
    positions = []
    for p in positions_raw or []:
        try:
            entry   = float(p.get("avg_entry_price") or 0)
            current = float(p.get("current_price") or p.get("market_value", 0))
            qty     = float(p.get("qty") or 0)
            mv      = float(p.get("market_value") or 0)
            pl_usd  = float(p.get("unrealized_pl") or 0)
            pl_pct  = float(p.get("unrealized_plpc") or 0) * 100
            positions.append({
                "symbol":         p.get("symbol"),
                "asset":          p.get("asset_class"),
                "side":           p.get("side"),
                "qty":            qty,
                "entry":          round(entry, 6),
                "current":        round(current, 6),
                "market_value":   round(mv, 2),
                "pl_usd":         round(pl_usd, 4),
                "pl_pct":         round(pl_pct, 3),
                "pct_of_equity":  round((mv / eq * 100) if eq else 0, 4),
            })
        except (TypeError, ValueError):
            continue

    # Recent orders (last 24h)
    after = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    orders_raw, err = _get("/v2/orders", {
        "status":    "all",
        "after":     after,
        "limit":     100,
        "direction": "desc",
    })
    if err:
        errors.append(f"orders: {err}")
        orders_raw = []
    orders = []
    for o in orders_raw or []:
        orders.append({
            "symbol":          o.get("symbol"),
            "side":            o.get("side"),
            "qty":             o.get("qty"),
            "type":            o.get("type"),
            "limit_price":     o.get("limit_price"),
            "status":          o.get("status"),
            "submitted_at":    o.get("submitted_at"),
            "filled_at":       o.get("filled_at"),
            "asset_class":     o.get("asset_class"),
            "client_order_id": o.get("client_order_id"),
        })

    # Read-only market quotes (VIXY as VIX proxy, SPY, QQQ) — IEX feed, no
    # broker calls, used for the morning-routine playbook.
    quotes_raw, err = _get(
        "/v2/stocks/quotes/latest",
        {"symbols": ",".join(QUOTE_SYMBOLS), "feed": "iex"},
        base=ALPACA_DATA_URL,
    )
    if err:
        errors.append(f"quotes: {err}")
        quotes_raw = {}
    quotes = {}
    for sym, q in (quotes_raw or {}).get("quotes", {}).items():
        try:
            quotes[sym] = {
                "ask": q.get("ap"),
                "bid": q.get("bp"),
                "mid": round((float(q.get("ap") or 0) + float(q.get("bp") or 0)) / 2, 4)
                       if q.get("ap") and q.get("bp") else None,
                "timestamp": q.get("t"),
            }
        except (TypeError, ValueError):
            continue

    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "account":   account_norm,
        "positions": positions,
        "orders":    orders,
        "quotes":    quotes,
        "errors":    errors,
    }

    # Single-line JSON for easy log parsing
    print(json.dumps(snapshot, default=str))
    return 0 if not errors else 0  # don't fail run on partial errors


if __name__ == "__main__":
    sys.exit(main())
