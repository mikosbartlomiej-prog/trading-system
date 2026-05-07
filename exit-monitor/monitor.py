"""
Exit Monitor — Hourly Position Manager
Sprawdza otwarte pozycje co godzinę i wysyla do Claude Routine decyzję exit/hold.
Używa Alpaca REST API bezpośrednio (bez MCP — GitHub Actions nie ma dostępu do MCP).
"""

import os
import sys
import json
import requests
from datetime import datetime, timezone, timedelta

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
    from notify import notify_exit, notify_summary
except ImportError:
    def notify_exit(*a, **k): pass
    def notify_summary(*a, **k): pass

# ─── Konfiguracja ────────────────────────────────────────────────────────────

ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"   # paper trading

CLOUDFLARE_WORKER_URL = os.environ.get("CLOUDFLARE_EXIT_WORKER_URL", "")

# Progi dla exit decyzji — Claude Routine dostanie te dane i podejmie decyzję
# v2.0 risk-on — looser thresholds, more patience, harder catastrophic stop
EXIT_THRESHOLDS = {
    "quick_profit_pct":      10.0,   # v2: was 3.0 — let winners run more
    "quick_profit_window_h":  6,     # v2: window for "quick" extended from 4h to 6h
    "time_decay_hours":       24,    # v2: was 6 — more patience for thesis to play out
    "flat_pnl_pct":           3.0,   # v2: was 1.0 — wider "flat" definition
    "leveraged_decay_hours":  96,    # v2: was 48 — 3× ETFs allowed to run
    "crypto_decay_hours":     48,    # v2: was 12 — give crypto room
    "crypto_decay_min_pl":    5.0,   # v2: was 3 — min profit to keep holding past decay
    "emergency_loss_pct":    -12.0,  # v2: was -5 — daily catastrophic, NOT per-trade SL
}

# ─── Alpaca REST API ──────────────────────────────────────────────────────────

def alpaca_get(endpoint: str) -> dict | list:
    """Wywołuje Alpaca REST API"""
    headers = {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }
    resp = requests.get(
        f"{ALPACA_BASE_URL}{endpoint}",
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_open_positions() -> list[dict]:
    """Pobiera wszystkie otwarte pozycje"""
    try:
        positions = alpaca_get("/v2/positions")
        return positions if isinstance(positions, list) else []
    except Exception as e:
        print(f"  Błąd pobierania pozycji: {e}")
        return []


def get_account_info() -> dict:
    """Pobiera informacje o koncie"""
    try:
        return alpaca_get("/v2/account")
    except Exception as e:
        print(f"  Błąd pobierania konta: {e}")
        return {}


def get_recent_orders(limit: int = 50) -> list[dict]:
    """Pobiera ostatnie zlecenia (do identyfikacji strategii)"""
    try:
        after = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        orders = alpaca_get(f"/v2/orders?status=all&limit={limit}&after={after}")
        return orders if isinstance(orders, list) else []
    except Exception as e:
        print(f"  Błąd pobierania zleceń: {e}")
        return []


# ─── Analiza pozycji ──────────────────────────────────────────────────────────

def enrich_position(pos: dict, orders: list[dict]) -> dict:
    """
    Wzbogaca pozycję o dodatkowe informacje:
    - czas trzymania
    - strategia źródłowa (z client_order_id)
    - rekomendacja wstępna
    """
    symbol        = pos.get("symbol", "")
    qty           = float(pos.get("qty", 0))
    side          = pos.get("side", "long")  # "long" or "short"
    entry_price   = float(pos.get("avg_entry_price", 0))
    current_price = float(pos.get("current_price", 0))
    unrealized_pl = float(pos.get("unrealized_pl", 0))
    unrealized_plpc = float(pos.get("unrealized_plpc", 0)) * 100  # w %

    # Znajdź zlecenie otwierające (najnowsze fill dla tego symbolu)
    strategy = "unknown"
    entry_time = None
    for order in sorted(orders, key=lambda o: o.get("filled_at") or "", reverse=True):
        if order.get("symbol") == symbol and order.get("filled_at"):
            client_id = order.get("client_order_id", "")
            # Format: strategy-TICKER-timestamp
            if "-" in client_id:
                strategy = client_id.split("-")[0]
            try:
                entry_time = datetime.fromisoformat(order["filled_at"].replace("Z", "+00:00"))
            except Exception:
                pass
            break

    # Czas trzymania
    now = datetime.now(timezone.utc)
    hold_hours = 0
    if entry_time:
        hold_hours = (now - entry_time).total_seconds() / 3600

    # Wstępna rekomendacja (Claude Routine podejmie ostateczną decyzję)
    recommendation = "HOLD"
    reasons = []

    if unrealized_plpc <= EXIT_THRESHOLDS["emergency_loss_pct"]:
        recommendation = "CLOSE_EMERGENCY"
        reasons.append(f"strata {unrealized_plpc:.1f}% przekracza próg awaryjny")

    elif unrealized_plpc >= EXIT_THRESHOLDS["quick_profit_pct"] and hold_hours < EXIT_THRESHOLDS["quick_profit_window_h"]:
        recommendation = "CONSIDER_TP"
        reasons.append(f"szybki zysk {unrealized_plpc:.1f}% w {hold_hours:.1f}h")

    elif strategy in ("leveraged-etf",) and hold_hours >= EXIT_THRESHOLDS["leveraged_decay_hours"]:
        recommendation = "CLOSE_DECAY"
        reasons.append(f"lewarowane ETF trzymane {hold_hours:.1f}h (próg: {EXIT_THRESHOLDS['leveraged_decay_hours']}h)")

    elif symbol in ("BTC/USD", "ETH/USD") and hold_hours >= EXIT_THRESHOLDS["crypto_decay_hours"] and unrealized_plpc < EXIT_THRESHOLDS["crypto_decay_min_pl"]:
        recommendation = "CLOSE_DECAY"
        reasons.append(f"crypto trzymane {hold_hours:.1f}h bez ≥3% zysku")

    elif hold_hours >= EXIT_THRESHOLDS["time_decay_hours"] and abs(unrealized_plpc) < EXIT_THRESHOLDS["flat_pnl_pct"]:
        recommendation = "CLOSE_FLAT"
        reasons.append(f"pozycja płaska ({unrealized_plpc:.1f}%) po {hold_hours:.1f}h")

    return {
        "symbol":          symbol,
        "qty":             qty,
        "side":            side,
        "strategy":        strategy,
        "entry_price":     entry_price,
        "current_price":   current_price,
        "unrealized_pl":   round(unrealized_pl, 2),
        "unrealized_plpc": round(unrealized_plpc, 2),
        "hold_hours":      round(hold_hours, 1),
        "recommendation":  recommendation,
        "reasons":         reasons,
    }


# ─── Wysyłanie do Claude Routine ─────────────────────────────────────────────

def send_to_routine(positions: list[dict], account: dict) -> bool:
    """Wysyła dane pozycji do Cloudflare Worker → Claude Routine"""
    if not CLOUDFLARE_WORKER_URL:
        print("  BRAK CLOUDFLARE_EXIT_WORKER_URL — pomijam wysyłanie")
        return False

    # Statystyki konta
    equity          = float(account.get("equity", 0))
    cash            = float(account.get("cash", 0))
    daily_pl        = float(account.get("equity", 0)) - float(account.get("last_equity", equity))
    daily_pl_pct    = (daily_pl / float(account.get("last_equity", equity or 1))) * 100 if equity else 0

    payload = {
        "type":            "exit_monitor",
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        "account": {
            "equity":       round(equity, 2),
            "cash":         round(cash, 2),
            "daily_pl":     round(daily_pl, 2),
            "daily_pl_pct": round(daily_pl_pct, 2),
        },
        "positions":       positions,
        "thresholds":      EXIT_THRESHOLDS,
        "summary": {
            "total_positions":    len(positions),
            "needs_attention":    sum(1 for p in positions if p["recommendation"] != "HOLD"),
            "total_unrealized_pl": round(sum(p["unrealized_pl"] for p in positions), 2),
        }
    }

    try:
        resp = requests.post(
            CLOUDFLARE_WORKER_URL,
            json=payload,
            timeout=30,
        )
        print(f"  Payload wysłany do Claude Routine: HTTP {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        print(f"  Błąd wysyłania: {e}")
        return False


# ─── Główna logika ────────────────────────────────────────────────────────────

def run_exit_check():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n[{now_str}] === EXIT MONITOR ===")

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("BŁĄD: Brak ALPACA_API_KEY lub ALPACA_SECRET_KEY")
        sys.exit(1)

    # Pobierz dane
    print("  Pobieranie pozycji i konta...")
    account   = get_account_info()
    positions = get_open_positions()
    orders    = get_recent_orders()

    print(f"  Otwartych pozycji: {len(positions)}")
    print(f"  Equity: ${float(account.get('equity', 0)):,.2f}")

    if not positions:
        print("  Brak otwartych pozycji — nic do sprawdzenia")
        return

    # Wzbogać pozycje o analizę
    enriched = []
    flagged  = []
    for pos in positions:
        ep = enrich_position(pos, orders)
        enriched.append(ep)
        if ep["recommendation"] != "HOLD":
            flagged.append(ep)
        status_icon = "⚠️" if ep["recommendation"] != "HOLD" else "✅"
        print(
            f"  {status_icon} {ep['symbol']:8s} {ep['side']:5s} "
            f"P&L: {ep['unrealized_plpc']:+.1f}% "
            f"({ep['hold_hours']:.1f}h) → {ep['recommendation']}"
            + (f" [{', '.join(ep['reasons'])}]" if ep['reasons'] else "")
        )

    # Email per flagged position (recommendation != HOLD)
    for ep in flagged:
        reason = "; ".join(ep["reasons"]) if ep["reasons"] else ep["recommendation"]
        notify_exit(ep["symbol"], ep["recommendation"], reason, ep["unrealized_plpc"])

    # Routine call only when at least one position is non-HOLD.
    # Calling routine with all-HOLD positions wastes daily routine budget
    # (~10 calls/day saved during quiet markets). Email summary still goes
    # for flagged positions regardless.
    if flagged:
        print(f"\n  Wysyłam do Claude Routine Exit Handler ({len(flagged)} flagged)...")
        send_to_routine(enriched, account)
    else:
        print(f"\n  Wszystkie pozycje HOLD — pomijam routine call (oszczędzam budget).")

    notify_summary("Exit Monitor", len(flagged), len(flagged))


# ─── Start ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_exit_check()
