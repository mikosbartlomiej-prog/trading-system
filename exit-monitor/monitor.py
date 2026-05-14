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


def _emergency_close_window_ok(ep: dict) -> bool:
    """
    True iff this position's asset class is currently tradeable.

    Pulled out so callers can DEFER (skip routine fallback) instead of
    routing market-closed cases to a routine that can't trade either —
    avoiding noisy "auth fail" reports when the real reason is "market
    closed, retry after open".
    """
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
        from instrument_windows import can_trade_now, _infer_asset_class
        symbol = ep.get("symbol", "")
        asset_class = _infer_asset_class(symbol)
        ok, reason = can_trade_now(symbol, asset_class=asset_class)
        if not ok:
            print(f"  emergency-close {symbol} ({asset_class}): deferred — {reason}")
            return False
        return True
    except ImportError:
        return True


def place_emergency_close(ep: dict) -> dict | None:
    """
    Close an exit-flagged position via Alpaca direct REST.

    Strategy (v3.4.3, 2026-05-13):
      1. PRIMARY: DELETE /v2/positions/{symbol} — canonical close endpoint
         that bypasses options buying-power checks (the failure mode that
         hit QQQ260518P00714000 today: "insufficient options buying power
         for cash-secured put" returned 403 on POST /v2/orders sell_to_close).
         DELETE explicitly references existing position → no buying-power
         requirement → reliable closure.
      2. FALLBACK: POST /v2/orders MARKET sell — used when DELETE returns
         non-2xx (e.g. position already closed by concurrent run).

    Bypasses the Claude.ai routine path entirely because the routine
    sandbox uses different (invalid) Alpaca keys that return 401.

    `ep` is the enriched-position dict from `enrich_position()`. Returns
    the Alpaca order JSON on success, None on failure.

    Reason tag in client_order_id:
      profit-lock | emergency | flat | decay
    (so analyzer can attribute close reasons separately).
    """
    import urllib.parse
    symbol = ep.get("symbol", "")
    qty    = abs(float(ep.get("qty", 0)))
    side   = ep.get("side", "long")
    if qty <= 0 or not symbol:
        return None

    # Note: trade-window check is done by caller via _emergency_close_window_ok
    # so blocked positions can be DEFERRED (skip routine fallback). Kept here
    # as a defensive no-op safety in case the helper is bypassed.

    # Reason tag for client_order_id (analyzer attribution).
    rec = ep.get("recommendation", "CLOSE_EMERGENCY")
    reason_tag = {
        "PROFIT_LOCK":     "profit-lock",
        "CLOSE_EMERGENCY": "emergency",
        "CLOSE_FLAT":      "flat",
        "CLOSE_DECAY":     "decay",
    }.get(rec, "emergency")
    ts = datetime.now(timezone.utc).strftime("%H%M%S%f")[:-3]
    safe_sym = symbol.replace("/", "").replace(" ", "")
    client_order_id = f"exit-{reason_tag}-{safe_sym}-{ts}"

    headers = {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }

    # PRIMARY: DELETE /v2/positions/{symbol} — bypasses buying-power bug
    enc_sym = urllib.parse.quote(symbol, safe="")
    try:
        r = requests.delete(
            f"{ALPACA_BASE_URL}/v2/positions/{enc_sym}",
            headers=headers,
            timeout=15,
        )
        if r.status_code in (200, 201, 207):
            body = r.json()
            print(f"  {reason_tag}-close DELETE OK: {symbol} → order_id={body.get('id','?')}")
            # Annotate body with our intended client_order_id for downstream parsing
            body["_client_order_intent"] = client_order_id
            return body
        if r.status_code == 404:
            print(f"  {reason_tag}-close DELETE 404: {symbol} not in positions (already closed)")
            return None
        # Non-success — log and try fallback
        print(f"  {reason_tag}-close DELETE error {r.status_code}: {r.text[:200]} — trying POST fallback")
    except Exception as e:
        print(f"  {reason_tag}-close DELETE exception: {e} — trying POST fallback")

    # FALLBACK: POST /v2/orders MARKET sell (original v3.3 path)
    close_side = "sell" if side == "long" else "buy"
    payload = {
        "symbol":          symbol,
        "qty":             str(int(qty)) if qty == int(qty) else str(qty),
        "side":            close_side,
        "type":            "market",
        "time_in_force":   "gtc" if "/" in symbol else "day",
        "client_order_id": client_order_id,
    }
    try:
        r = requests.post(
            f"{ALPACA_BASE_URL}/v2/orders",
            headers=headers,
            json=payload,
            timeout=15,
        )
        if r.status_code in (200, 201):
            return r.json()
        print(f"  {reason_tag}-close POST error {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        print(f"  {reason_tag}-close POST exception: {e}")
        return None


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

    # Profit-lock cascade — gdy daily P&L retraced >=50% od peak >=$1k,
    # aggressively close winners. New since 2026-05-13 (response to
    # 2026-05-12 disaster: +$3,173 peak → -$184 reversal).
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
        from peak_tracker import should_profit_lock, VERDICT_PROFIT_LOCK
        in_lock, peak_data = should_profit_lock()
    except (ImportError, Exception):
        in_lock = False
        peak_data = {}

    if in_lock and unrealized_plpc >= 8.0:
        # Aggressive harvest: any winner >=8% gets flagged. The 8% threshold
        # is loose vs the standard CONSIDER_TP +10% because lock mode is
        # specifically defending an already-realized peak we are retracing.
        recommendation = "PROFIT_LOCK"
        reasons.append(
            f"PROFIT-LOCK active: peak ${peak_data.get('peak_pl_usd',0):+.0f}, "
            f"retrace {peak_data.get('retrace_from_peak',0):.0%}, "
            f"this winner {unrealized_plpc:.1f}% — harvest now"
        )

    elif unrealized_plpc <= EXIT_THRESHOLDS["emergency_loss_pct"]:
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

    # ── Peak tracker — update daily P&L peak + retrace verdict ───────────
    # New 2026-05-13: solves 2026-05-12 disaster where +$3,173 peak ended
    # at -$184 with zero protective action. update_peak() persists peak +
    # current to state.json::daily_peak; verdict triggers profit-lock
    # cascade in enrich_position when retrace >= 50% from peak >= $1k.
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
        from peak_tracker import (update_peak, summarize, alert_already_sent_today,
                                    mark_alert_sent, VERDICT_WARN, VERDICT_PROFIT_LOCK)
        # Pass account_status-like dict (exit-monitor's get_account_info has the fields)
        peak = update_peak({
            "equity":       float(account.get("equity", 0) or 0),
            "last_equity":  float(account.get("last_equity", 0) or 0),
        })
        print(f"  Peak tracker: {summarize(peak)}")
        # Email alerts (dedup per UTC day)
        verdict = peak.get("verdict", "")
        if verdict in (VERDICT_WARN, VERDICT_PROFIT_LOCK) and not alert_already_sent_today(verdict):
            try:
                from notify import notify_peak_retrace
                ok = notify_peak_retrace(peak, level=verdict)
                if ok:
                    mark_alert_sent(verdict)
                    print(f"  [PEAK-ALERT] {verdict} email sent")
            except Exception as e:
                print(f"  peak_tracker notify failed: {e}")
    except Exception as e:
        print(f"  peak_tracker unavailable ({type(e).__name__}: {e}) — skip")

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

    # ── EMERGENCY + PROFIT_LOCK EXITS: bypass routine, place MARKET directly ─
    # CLOSE_EMERGENCY: position breaches -12% stop. Time-critical.
    # PROFIT_LOCK: daily P&L retraced 50%+ from peak >=$1k. Lock unrealized
    #              gains now before further reversal.
    # CLOSE_FLAT: long-hold flat position — close to free margin.
    # CLOSE_DECAY: leveraged ETF / crypto past time-decay window.
    # All four → direct REST via place_emergency_close (DELETE primary,
    # POST fallback). Routine ONLY used for CONSIDER_TP (less critical;
    # LLM evaluates if profit worth taking now or letting run).
    #
    # v3.4.5 (2026-05-14): trade-window-blocked positions are DEFERRED
    # (not routed to routine). The routine sandbox uses different Alpaca
    # keys (401 auth fail) and also cannot trade options outside market
    # hours — so falling back produces noisy "auth fail" reports without
    # accomplishing anything. Better to log "deferred" and let next cron
    # tick (post-market-open) retry.
    direct_recs = ("CLOSE_EMERGENCY", "PROFIT_LOCK", "CLOSE_FLAT", "CLOSE_DECAY")
    direct_close = [ep for ep in flagged if ep["recommendation"] in direct_recs]
    other_flagged = [ep for ep in flagged if ep["recommendation"] not in direct_recs]
    emergency = direct_close
    closed_directly = 0
    deferred_count = 0
    for ep in emergency:
        # Trade-window pre-check: skip both DELETE and routine fallback if
        # market closed for this instrument's asset class (e.g. options
        # outside 13:30-20:00 UTC).
        if not _emergency_close_window_ok(ep):
            deferred_count += 1
            continue
        result = place_emergency_close(ep)
        if result:
            print(f"  {ep['recommendation']} closed directly: {ep['symbol']} qty={ep['qty']} "
                  f"id={result.get('id', '?')}")
            closed_directly += 1
        else:
            print(f"  {ep['recommendation']} close FAILED for {ep['symbol']} — "
                  f"falling back to routine")
            other_flagged.append(ep)  # routine as last resort

    # Routine call only for non-emergency flagged positions (mostly CONSIDER_TP)
    if other_flagged:
        print(f"\n  Wysyłam do Claude Routine Exit Handler ({len(other_flagged)} flagged, "
              f"{closed_directly} closed directly, {deferred_count} deferred)...")
        send_to_routine(enriched, account)
    elif emergency:
        print(f"\n  {closed_directly} closed directly via REST, "
              f"{deferred_count} deferred (market closed) — no routine call needed")
    else:
        print(f"\n  Wszystkie pozycje HOLD — pomijam routine call (oszczędzam budget).")

    notify_summary("Exit Monitor", len(flagged), len(flagged))


# ─── Start ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_exit_check()
