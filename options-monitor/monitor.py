"""
Options Monitor — Calls/Puts on momentum signals.

Detects momentum setups (RSI 45-65 -> CALL, RSI > 72 -> PUT) on a curated
ticker whitelist and forwards an options *proposal* to a Claude Routine via
the Cloudflare Worker. The routine resolves the actual contract (IV, premium,
greeks) via Alpaca MCP and asks the user for explicit approval before placing
an order — enforcing the iron rule "Options require explicit user approval".

This monitor INTENTIONALLY does not place trades and does not need a paid
Alpaca options-data subscription. It only emits proposals.
"""

import os
import sys
import time
import requests
from datetime import datetime, timezone, timedelta

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
    from notify import notify_signal, notify_summary
    from risk_guards import vix_guard
except ImportError:
    def notify_signal(*a, **k): pass
    def notify_summary(*a, **k): pass
    def vix_guard(): return ("OK", 1.0)

# ─── Konfiguracja ────────────────────────────────────────────────────────────

ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"
FINNHUB_API_KEY   = os.environ.get("FINNHUB_API_KEY", "")
CLOUDFLARE_WORKER_URL = os.environ.get("CLOUDFLARE_OPTIONS_WORKER_URL", "")

# Whitelist — same liquid names the equity monitors already watch
TICKERS = [
    "AAPL", "MSFT", "GOOGL", "NVDA", "META", "AMZN", "TSLA",
    "SPY", "QQQ", "JPM", "RTX", "LMT",
]

# Strategy parameters (strategies/options-strategy.md)
SIZE_USD                 = 500     # USD per signal
MAX_CONTRACTS_PER_SIGNAL = 2
MAX_OPEN_OPTIONS         = 3       # global cap across all underlyings
DTE_MIN                  = 14
DTE_MAX                  = 21
IV_MAX_CALL_PCT          = 35.0
IV_MAX_PUT_PCT           = 45.0
RSI_CALL_MIN             = 45
RSI_CALL_MAX             = 65
RSI_PUT_MIN              = 72
TP_PREMIUM_MULT          = 1.80    # +80%
SL_PREMIUM_MULT          = 0.50    # -50%
STRIKE_OTM_MAX_PCT       = 3.0     # ATM ±3%
EARNINGS_BUFFER_DAYS     = 1       # avoid options ±1 day around earnings


# ─── Finnhub helpers ─────────────────────────────────────────────────────────

def finnhub_get(endpoint: str, params: dict) -> dict | None:
    if not FINNHUB_API_KEY:
        return None
    params = {**params, "token": FINNHUB_API_KEY}
    try:
        r = requests.get(f"https://finnhub.io/api/v1{endpoint}", params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  Finnhub {endpoint} error: {e}")
        return None


def get_candles(ticker: str, days: int = 35) -> dict | None:
    now = int(datetime.now().timestamp())
    frm = int((datetime.now() - timedelta(days=days + 5)).timestamp())
    data = finnhub_get("/stock/candle", {
        "symbol":     ticker,
        "resolution": "D",
        "from":       frm,
        "to":         now,
    })
    if not data or data.get("s") != "ok" or not data.get("c"):
        return None
    return data


def calculate_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas  = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains   = [d if d > 0 else 0 for d in deltas]
    losses  = [-d if d < 0 else 0 for d in deltas]
    avg_g   = sum(gains[-period:]) / period
    avg_l   = sum(losses[-period:]) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - (100.0 / (1.0 + rs))


def is_earnings_imminent(ticker: str) -> bool:
    """True if Finnhub earnings calendar shows earnings within EARNINGS_BUFFER_DAYS."""
    today = datetime.now().date()
    frm   = (today - timedelta(days=EARNINGS_BUFFER_DAYS)).isoformat()
    to    = (today + timedelta(days=EARNINGS_BUFFER_DAYS + DTE_MAX)).isoformat()
    data  = finnhub_get("/calendar/earnings", {"from": frm, "to": to, "symbol": ticker})
    if not data:
        return False
    for ev in data.get("earningsCalendar", []) or []:
        try:
            ev_date = datetime.fromisoformat(ev["date"]).date()
        except Exception:
            continue
        if abs((ev_date - today).days) <= EARNINGS_BUFFER_DAYS:
            return True
    return False


# ─── Alpaca helpers ──────────────────────────────────────────────────────────

def count_open_options() -> int:
    """How many options positions does the account currently hold?"""
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        return 0
    try:
        r = requests.get(
            f"{ALPACA_BASE_URL}/v2/positions",
            headers={
                "APCA-API-KEY-ID":     ALPACA_API_KEY,
                "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
            },
            timeout=15,
        )
        r.raise_for_status()
        positions = r.json() or []
        return sum(1 for p in positions if p.get("asset_class") == "us_option")
    except Exception as e:
        print(f"  Pozycje Alpaca error: {e}")
        return 0


# ─── Sygnał ──────────────────────────────────────────────────────────────────

def build_proposal(ticker: str) -> dict | None:
    candles = get_candles(ticker)
    if not candles:
        return None

    closes = candles["close"]
    spot   = closes[-1]
    rsi    = calculate_rsi(closes)
    if rsi is None:
        return None

    if RSI_CALL_MIN <= rsi <= RSI_CALL_MAX:
        opt_type, action, iv_max = "call", "BUY_TO_OPEN_CALL", IV_MAX_CALL_PCT
    elif rsi > RSI_PUT_MIN:
        opt_type, action, iv_max = "put",  "BUY_TO_OPEN_PUT",  IV_MAX_PUT_PCT
    else:
        print(f"  {ticker}: RSI={rsi:.1f} -> brak setupu")
        return None

    if is_earnings_imminent(ticker):
        print(f"  {ticker}: earnings ±{EARNINGS_BUFFER_DAYS}d -> pomijam")
        return None

    today      = datetime.now().date()
    expiry_min = (today + timedelta(days=DTE_MIN)).isoformat()
    expiry_max = (today + timedelta(days=DTE_MAX)).isoformat()

    return {
        "type":              "options_proposal",
        "symbol":            ticker,
        "spot":              round(spot, 2),
        "rsi":               round(rsi, 1),
        "option_type":       opt_type,
        "action":            action,
        "strategy":          "options-momentum",
        "strike_target":     round(spot, 1),
        "strike_min":        round(spot * (1 - STRIKE_OTM_MAX_PCT / 100), 2),
        "strike_max":        round(spot * (1 + STRIKE_OTM_MAX_PCT / 100), 2),
        "expiry_min":        expiry_min,
        "expiry_max":        expiry_max,
        "iv_max_pct":        iv_max,
        "size_usd":          SIZE_USD,
        "max_contracts":     MAX_CONTRACTS_PER_SIGNAL,
        "tp_premium_mult":   TP_PREMIUM_MULT,
        "sl_premium_mult":   SL_PREMIUM_MULT,
        "requires_approval": True,
    }


def send_proposal(proposal: dict) -> bool:
    if not CLOUDFLARE_WORKER_URL:
        print("  BRAK CLOUDFLARE_OPTIONS_WORKER_URL — pomijam wysyłanie")
        return False
    try:
        r = requests.post(CLOUDFLARE_WORKER_URL, json=proposal, timeout=30)
        print(f"  Proposal {proposal['action']} {proposal['symbol']}: HTTP {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        print(f"  Błąd wysyłania proposal: {e}")
        return False


# ─── Main ────────────────────────────────────────────────────────────────────

def run_scan():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{now}] === OPTIONS MONITOR ===")

    if not FINNHUB_API_KEY:
        print("BŁĄD: brak FINNHUB_API_KEY")
        sys.exit(1)

    vix_status, size_mult = vix_guard()
    if vix_status == "HALT":
        notify_summary("Options Monitor", 0, 0)
        return

    open_count = count_open_options()
    if open_count >= MAX_OPEN_OPTIONS:
        print(f"  Otwartych opcji: {open_count}/{MAX_OPEN_OPTIONS} -> brak miejsca, pomijam skan")
        notify_summary("Options Monitor", 0, 0)
        return
    slots_left = MAX_OPEN_OPTIONS - open_count
    print(f"  Otwartych opcji: {open_count}/{MAX_OPEN_OPTIONS} (slotów: {slots_left})")

    proposals = []
    for ticker in TICKERS:
        proposal = build_proposal(ticker)
        if proposal:
            proposal["size_usd"] = round(proposal["size_usd"] * size_mult)
            proposals.append(proposal)
        time.sleep(0.5)

    print(f"  Znalezione propozycje: {len(proposals)}")
    sent = 0
    for proposal in proposals[:slots_left]:
        ok = send_proposal(proposal)
        if ok:
            sent += 1
        notify_signal(proposal, ok)

    notify_summary("Options Monitor", len(proposals), sent)
    print(f"[{now}] Wysłano: {sent}/{len(proposals)}\n")


if __name__ == "__main__":
    run_scan()
