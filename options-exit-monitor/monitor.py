"""
Options Exit Monitor — emulates bracket TP/SL for paper options positions.

Alpaca paper does not support bracket/OCO/stop order classes for options,
so this monitor polls every few minutes during market hours, evaluates
each open options position against the strategy's TP/SL multipliers
(+80% / -50% of entry premium) and places a SELL-to-close LIMIT order
when a threshold is hit.

De-dup: skips a position if there is already an open SELL order for the
same contract symbol (prevents stacking duplicate exits across runs).
"""

import os
import sys
import requests
from datetime import datetime, timezone

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
    from notify import notify_exit, notify_summary
except ImportError:
    def notify_exit(*a, **k): pass
    def notify_summary(*a, **k): pass

ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"

TP_PREMIUM_MULT = 1.80   # take profit at +80% premium (matches options-monitor)
SL_PREMIUM_MULT = 0.50   # stop loss at -50% premium  (matches options-monitor)


def alpaca_headers() -> dict:
    return {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }


# ─── Alpaca helpers ──────────────────────────────────────────────────────────

def get_open_options_positions() -> list[dict]:
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/v2/positions",
                         headers=alpaca_headers(), timeout=15)
        r.raise_for_status()
        return [p for p in (r.json() or []) if p.get("asset_class") == "us_option"]
    except Exception as e:
        print(f"  /v2/positions error: {e}")
        return []


def already_has_open_sell(contract_symbol: str) -> bool:
    """True if there is an open SELL order for this contract."""
    try:
        r = requests.get(
            f"{ALPACA_BASE_URL}/v2/orders",
            headers=alpaca_headers(),
            params={"status": "open", "symbols": contract_symbol},
            timeout=15,
        )
        r.raise_for_status()
        return any(o.get("side") == "sell" for o in (r.json() or []))
    except Exception as e:
        print(f"  open-orders check error: {e}")
        return False  # fail open -> may attempt a duplicate; rare


def place_sell_to_close(contract_symbol: str, qty: int, limit_price: float) -> dict | None:
    """Place a simple SELL-to-close LIMIT order on the contract."""
    payload = {
        "symbol":        contract_symbol,
        "qty":           str(int(qty)),
        "side":          "sell",
        "type":          "limit",
        "limit_price":   str(round(limit_price, 2)),
        "time_in_force": "day",
    }
    try:
        r = requests.post(f"{ALPACA_BASE_URL}/v2/orders",
                          headers=alpaca_headers(), json=payload, timeout=15)
        if r.status_code in (200, 201):
            return r.json()
        print(f"  sell-to-close error {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        print(f"  sell-to-close exception: {e}")
        return None


# ─── Decision ────────────────────────────────────────────────────────────────

def evaluate(pos: dict) -> tuple[str, float | None, float, str]:
    """
    Returns (decision, exit_limit_price, pl_pct, reason).
    decision: "TP" | "SL" | "HOLD"
    """
    try:
        qty     = abs(float(pos.get("qty", 0)))
        entry   = float(pos.get("avg_entry_price", 0))
        current = float(pos.get("current_price", 0))
    except (TypeError, ValueError):
        return ("HOLD", None, 0.0, "non-numeric position fields")

    if entry <= 0 or current <= 0 or qty <= 0:
        return ("HOLD", None, 0.0, "missing entry / current / qty")

    pl_pct = (current - entry) / entry * 100
    tp_lvl = entry * TP_PREMIUM_MULT
    sl_lvl = entry * SL_PREMIUM_MULT

    if current >= tp_lvl:
        return ("TP", tp_lvl, pl_pct,
                f"current ${current:.2f} >= TP ${tp_lvl:.2f} (+{pl_pct:.1f}%)")
    if current <= sl_lvl:
        return ("SL", current, pl_pct,
                f"current ${current:.2f} <= SL ${sl_lvl:.2f} ({pl_pct:.1f}%)")
    return ("HOLD", None, pl_pct,
            f"in window (pl {pl_pct:+.1f}%, TP=${tp_lvl:.2f}, SL=${sl_lvl:.2f})")


# ─── Main ────────────────────────────────────────────────────────────────────

def run_exit_check():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n[{now}] === OPTIONS EXIT MONITOR ===")

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("BŁĄD: brak ALPACA_API_KEY / ALPACA_SECRET_KEY")
        sys.exit(1)

    positions = get_open_options_positions()
    print(f"  Otwartych opcji: {len(positions)}")
    if not positions:
        return

    flagged = 0
    closed  = 0
    for pos in positions:
        symbol = pos["symbol"]
        decision, exit_price, pl_pct, reason = evaluate(pos)
        print(f"  {symbol}: {reason} -> {decision}")
        if decision == "HOLD":
            continue
        flagged += 1

        if already_has_open_sell(symbol):
            print(f"    pominięty — sell-to-close juz wystawiony")
            continue

        qty   = abs(float(pos["qty"]))
        order = place_sell_to_close(symbol, qty, exit_price)
        if order:
            print(f"    SELL placed: id={order.get('id')} status={order.get('status')}")
            closed += 1
            notify_exit(symbol, f"SELL_TO_CLOSE_{decision}", reason, pl_pct)
        else:
            # Sell rejected — surface via summary anyway
            print(f"    SELL ODRZUCONY przez Alpaca")

    notify_summary("Options Exit Monitor", flagged, closed)
    print(f"[{now}] Flagged={flagged}, sells placed={closed}\n")


if __name__ == "__main__":
    run_exit_check()
