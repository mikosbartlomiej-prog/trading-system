"""
Direct Alpaca REST order placement.

Replaces the routine-based execution path that was burning the 15-call
daily Anthropic Routines budget. Each monitor now places orders directly
via /v2/orders, mirroring the options-monitor pattern that's been live
since 2026-05-06.

Helpers cover three asset classes:

  place_stock_bracket(symbol, side, qty, entry, sl, tp, strategy)
      Bracket order for stocks/ETFs (Alpaca paper supports brackets).
      side: "buy" (long) or "sell_short" (short)

  place_crypto_order(symbol, side, qty, entry, strategy)
      Simple limit order for BTC/USD, ETH/USD. Alpaca crypto does NOT
      support bracket — TP/SL must be managed separately by exit-monitor.

  place_simple_buy(symbol, qty, limit_price, strategy)
      Simple limit BUY for options (Alpaca paper rejects bracket on
      options — already used by options-monitor).

  get_latest_quote(symbol)
      Single-quote snapshot for SL/TP price computation. Returns
      {bid, ask, mid} or None.

All helpers fail-open: API failure returns None, caller falls through
to email-only / log path. Same fail-open philosophy as risk_guards.
"""

import os
import urllib.parse
import requests
from datetime import datetime, timezone

ALPACA_BASE_URL = "https://paper-api.alpaca.markets"
ALPACA_DATA_URL = "https://data.alpaca.markets"


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID":     os.environ.get("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.environ.get("ALPACA_SECRET_KEY", ""),
    }


def _client_order_id(strategy: str, symbol: str) -> str:
    """Per-strategy client_order_id so exit-monitor can identify origin."""
    ts = datetime.now(timezone.utc).strftime("%H%M%S%f")[:-3]
    safe_sym = symbol.replace("/", "").replace(" ", "")
    return f"{strategy}-{safe_sym}-{ts}"


# ─── Quote / spot price ───────────────────────────────────────────────────────

def get_latest_quote(symbol: str) -> dict | None:
    """
    Returns {bid, ask, mid} for `symbol`, or None on failure.

    Used by entry monitors that need a current spot price to compute
    SL/TP from percentage thresholds.
    """
    if not _headers()["APCA-API-KEY-ID"]:
        return None
    try:
        r = requests.get(
            f"{ALPACA_DATA_URL}/v2/stocks/{urllib.parse.quote(symbol, safe='')}/quotes/latest",
            headers=_headers(),
            params={"feed": "iex"},
            timeout=10,
        )
        r.raise_for_status()
        q = r.json().get("quote", {})
        bid = float(q.get("bp", 0))
        ask = float(q.get("ap", 0))
        if bid <= 0 or ask <= 0:
            return None
        return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2.0}
    except Exception as e:
        print(f"  quote {symbol} error: {e}")
        return None


def get_latest_crypto_quote(symbol: str) -> dict | None:
    """Returns {bid, ask, mid} for crypto symbol like 'BTC/USD'."""
    if not _headers()["APCA-API-KEY-ID"]:
        return None
    try:
        r = requests.get(
            f"{ALPACA_DATA_URL}/v1beta3/crypto/us/latest/quotes",
            headers=_headers(),
            params={"symbols": symbol},
            timeout=10,
        )
        r.raise_for_status()
        d = r.json().get("quotes", {}).get(symbol, {})
        bid = float(d.get("bp", 0))
        ask = float(d.get("ap", 0))
        if bid <= 0 or ask <= 0:
            return None
        return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2.0}
    except Exception as e:
        print(f"  crypto quote {symbol} error: {e}")
        return None


# ─── Order placement ──────────────────────────────────────────────────────────

def place_stock_bracket(symbol: str, side: str, qty: int,
                        entry_price: float, stop_loss: float,
                        take_profit: float,
                        strategy: str = "auto") -> dict | None:
    """
    Place a bracket order for stocks/ETFs.

    side:        "buy" (long) or "sell_short" (short)
    qty:         integer shares (>= 1)
    entry_price: limit price for entry leg
    stop_loss:   absolute price for SL leg
    take_profit: absolute price for TP leg
    strategy:    used in client_order_id prefix

    Returns the Alpaca order JSON on success, None on failure (incl.
    risk-officer REJECT — see shared.risk_officer.evaluate_trade).
    """
    if qty < 1 or entry_price <= 0 or stop_loss <= 0 or take_profit <= 0:
        print(f"  bracket reject: qty={qty} entry={entry_price} sl={stop_loss} tp={take_profit}")
        return None
    if side not in ("buy", "sell_short"):
        print(f"  bracket reject: bad side '{side}'")
        return None

    # Risk-officer gate (opt-out via USE_RISK_OFFICER=false). Hard violations
    # block the trade; soft warnings are logged but don't reject. Fail-soft
    # if the officer module is unavailable for any reason — proceed to place.
    try:
        from risk_officer import evaluate_trade  # noqa: E402
        verdict = evaluate_trade({
            "symbol":      symbol,
            "action":      "BUY" if side == "buy" else "SELL_SHORT",
            "size_usd":    qty * entry_price,
            "entry_price": entry_price,
            "stop_loss":   stop_loss,
            "take_profit": take_profit,
            "strategy":    strategy,
        })
        if verdict.get("decision") == "REJECT":
            print(f"  RISK-OFFICER REJECT {symbol}: {verdict['rationale']}")
            for f in verdict.get("checks_failed", []):
                print(f"    - {f}")
            return None
        if verdict.get("warnings"):
            print(f"  risk-officer warnings ({symbol}):")
            for w in verdict["warnings"]:
                print(f"    - {w}")
    except Exception as e:
        print(f"  risk-officer unavailable ({type(e).__name__}: {e}); proceeding")

    payload = {
        "symbol":         symbol,
        "qty":            str(int(qty)),
        "side":           side,
        "type":           "limit",
        "limit_price":    str(round(entry_price, 2)),
        "time_in_force":  "day",
        "order_class":    "bracket",
        "take_profit":    {"limit_price": str(round(take_profit, 2))},
        "stop_loss":      {"stop_price":  str(round(stop_loss, 2))},
        "client_order_id": _client_order_id(strategy, symbol),
    }
    try:
        r = requests.post(f"{ALPACA_BASE_URL}/v2/orders",
                          headers=_headers(), json=payload, timeout=15)
        if r.status_code in (200, 201):
            return r.json()
        print(f"  Alpaca bracket error {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        print(f"  Alpaca bracket exception: {e}")
        return None


def place_crypto_order(symbol: str, side: str, qty: float,
                       limit_price: float,
                       strategy: str = "auto") -> dict | None:
    """
    Place a simple limit order for crypto (Alpaca crypto does NOT support
    bracket / OCO).

    SL/TP must be managed separately — exit-monitor's crypto thresholds
    (CRYPTO_DECAY_HOURS=48 in v2.0, plus per-position trailing) handle
    exit timing.
    """
    if qty <= 0 or limit_price <= 0:
        return None
    if side not in ("buy", "sell"):
        return None

    # Risk-officer gate. Crypto orders don't carry SL/TP at the broker
    # (Alpaca crypto = simple limit only); we pass the strategy-level
    # values so the officer can validate R:R and per-trade size.
    try:
        from risk_officer import evaluate_trade  # noqa: E402
        # For crypto, look up SL/TP from strategy defaults if available.
        # If caller didn't compute them, the officer treats no-TP as a
        # soft-warning trailing-exit assumption (won't reject).
        verdict = evaluate_trade({
            "symbol":      symbol,
            "action":      "BUY" if side == "buy" else "SELL_SHORT",
            "size_usd":    qty * limit_price,
            "entry_price": limit_price,
            "stop_loss":   limit_price * 0.93 if side == "buy" else limit_price * 1.07,
            "take_profit": limit_price * 1.20 if side == "buy" else limit_price * 0.80,
            "strategy":    strategy,
        })
        if verdict.get("decision") == "REJECT":
            print(f"  RISK-OFFICER REJECT {symbol}: {verdict['rationale']}")
            for f in verdict.get("checks_failed", []):
                print(f"    - {f}")
            return None
        if verdict.get("warnings"):
            print(f"  risk-officer warnings ({symbol}):")
            for w in verdict["warnings"]:
                print(f"    - {w}")
    except Exception as e:
        print(f"  risk-officer unavailable ({type(e).__name__}: {e}); proceeding")

    payload = {
        "symbol":         symbol,
        "qty":            str(qty),
        "side":           side,
        "type":           "limit",
        "limit_price":    str(round(limit_price, 2)),
        "time_in_force":  "gtc",   # crypto requires gtc
        "client_order_id": _client_order_id(strategy, symbol),
    }
    try:
        r = requests.post(f"{ALPACA_BASE_URL}/v2/orders",
                          headers=_headers(), json=payload, timeout=15)
        if r.status_code in (200, 201):
            return r.json()
        print(f"  Alpaca crypto order error {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        print(f"  Alpaca crypto order exception: {e}")
        return None


def place_simple_buy(symbol: str, qty: int, limit_price: float,
                     strategy: str = "auto") -> dict | None:
    """
    Simple limit BUY for instruments that don't support brackets.
    Used by options-monitor (Alpaca paper rejects bracket on options).
    """
    if qty < 1 or limit_price <= 0:
        return None
    payload = {
        "symbol":         symbol,
        "qty":            str(int(qty)),
        "side":           "buy",
        "type":           "limit",
        "limit_price":    str(round(limit_price, 2)),
        "time_in_force":  "day",
        "client_order_id": _client_order_id(strategy, symbol),
    }
    try:
        r = requests.post(f"{ALPACA_BASE_URL}/v2/orders",
                          headers=_headers(), json=payload, timeout=15)
        if r.status_code in (200, 201):
            return r.json()
        print(f"  Alpaca simple buy error {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        print(f"  Alpaca simple buy exception: {e}")
        return None


# ─── High-level signal-to-order adapter ───────────────────────────────────────

def execute_stock_signal(signal: dict) -> dict | None:
    """
    Convert a monitor's signal dict into a bracket order via Alpaca.

    Expected `signal` shape (matches what monitors produce today):
      {
        "symbol":      "RTX",
        "action":      "BUY" | "SELL_SHORT",
        "size_usd":    8000,
        "stop_loss":   absolute_price OR None (then we use sl_pct),
        "take_profit": absolute_price OR None,
        "sl_pct":      e.g. -5.0  (used when stop_loss is None)
        "tp_pct":      e.g. +12.0
        "strategy":    name string
      }

    Returns Alpaca order on success, None on any failure (caller falls
    through to email-only logging).
    """
    sym       = signal["symbol"]
    action    = signal["action"]
    size_usd  = float(signal.get("size_usd", 0))
    strategy  = signal.get("strategy", "auto")

    if size_usd <= 0:
        print(f"  {sym}: size_usd={size_usd} -> skip")
        return None

    side = "buy" if action.upper() == "BUY" else "sell_short"

    # If signal already has absolute SL/TP, use them. Else compute from %.
    sl_abs = signal.get("stop_loss")
    tp_abs = signal.get("take_profit")
    entry  = None

    if sl_abs and tp_abs:
        # Need a fresh entry price. Use mid of latest quote.
        q = get_latest_quote(sym)
        if not q:
            print(f"  {sym}: quote unavailable -> skip")
            return None
        entry = q["mid"]
    else:
        # Fallback path: SL/TP given as percentages
        sl_pct = float(signal.get("sl_pct", 0))
        tp_pct = float(signal.get("tp_pct", 0))
        if not sl_pct or not tp_pct:
            print(f"  {sym}: missing SL/TP -> skip")
            return None
        q = get_latest_quote(sym)
        if not q:
            print(f"  {sym}: quote unavailable -> skip")
            return None
        entry = q["mid"]
        if side == "buy":
            sl_abs = entry * (1 + sl_pct / 100.0)   # sl_pct is negative
            tp_abs = entry * (1 + tp_pct / 100.0)
        else:
            sl_abs = entry * (1 - sl_pct / 100.0)
            tp_abs = entry * (1 - tp_pct / 100.0)

    qty = max(1, int(size_usd / entry))

    return place_stock_bracket(
        symbol      = sym,
        side        = side,
        qty         = qty,
        entry_price = entry,
        stop_loss   = round(sl_abs, 2),
        take_profit = round(tp_abs, 2),
        strategy    = strategy,
    )


def execute_crypto_signal(signal: dict) -> dict | None:
    """
    Crypto entry: simple limit at mid. SL/TP managed by exit-monitor
    crypto thresholds (Alpaca crypto = no bracket support).
    """
    sym      = signal["symbol"]
    action   = signal["action"]
    size_usd = float(signal.get("size_usd", 0))
    strategy = signal.get("strategy", "crypto-momentum")

    if size_usd <= 0:
        return None

    side = "buy" if action.upper() in ("BUY", "BUY_TO_OPEN") else "sell"

    q = get_latest_crypto_quote(sym)
    if not q:
        print(f"  {sym}: crypto quote unavailable -> skip")
        return None
    entry = q["mid"]
    qty = round(size_usd / entry, 4)
    if qty <= 0:
        return None

    return place_crypto_order(
        symbol      = sym,
        side        = side,
        qty         = qty,
        limit_price = entry,
        strategy    = strategy,
    )
