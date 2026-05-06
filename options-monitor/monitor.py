"""
Options Monitor — Calls/Puts on momentum signals (auto-execute on paper).

Detects momentum setups (RSI 45-65 -> CALL, RSI > 72 -> PUT) on a curated
ticker whitelist and either:
  - AUTO_EXECUTE_OPTIONS=true (default): resolves the contract via Alpaca
    /v2/options/contracts (no paid options-data subscription needed) and
    places a bracket buy_to_open order directly via Alpaca REST. Sends an
    [EXECUTED] confirmation email with the OCC contract symbol + order id.
  - AUTO_EXECUTE_OPTIONS=false: forwards an options *proposal* to a Claude
    Routine via Cloudflare Worker (legacy path; subject to Anthropic
    Routines rate-limit / 429s).

Iron-rule preservation under auto-execute on paper:
  - paper account only (no real money)
  - per-run cap = MAX_PROPOSALS_PER_RUN
  - global cap = MAX_OPEN_OPTIONS open option positions
  - $500 budget per signal, 1 contract per fill
  - earnings ±1d skip, ATM ±3% strike window, DTE 14-21
  - VIX HALT at 45+, CAUTION (50% sizing) at 35+
"""

import os
import sys
import time
import requests
from datetime import datetime, timezone, timedelta

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
    from notify import notify_signal, notify_summary, notify_order_executed
    from risk_guards import vix_guard
    from market_data import get_daily_bars
except ImportError:
    def notify_signal(*a, **k): pass
    def notify_summary(*a, **k): pass
    def notify_order_executed(*a, **k): pass
    def vix_guard(): return ("OK", 1.0)
    def get_daily_bars(symbol, days=35): return None

# ─── Konfiguracja ────────────────────────────────────────────────────────────

ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"
FINNHUB_API_KEY   = os.environ.get("FINNHUB_API_KEY", "")
CLOUDFLARE_WORKER_URL = os.environ.get("CLOUDFLARE_OPTIONS_WORKER_URL", "")
AUTO_EXECUTE      = os.environ.get("AUTO_EXECUTE_OPTIONS", "true").lower() == "true"

# Whitelist — same liquid names the equity monitors already watch
TICKERS = [
    "AAPL", "MSFT", "GOOGL", "NVDA", "META", "AMZN", "TSLA",
    "SPY", "QQQ", "JPM", "RTX", "LMT",
]

# Strategy parameters (strategies/options-strategy.md)
SIZE_USD                 = 500     # USD per signal
MAX_CONTRACTS_PER_SIGNAL = 2
MAX_OPEN_OPTIONS         = 3       # global cap across all underlyings
MAX_PROPOSALS_PER_RUN    = 1       # per-run cap (also rate-limit safety in routine path)
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


def alpaca_headers() -> dict:
    return {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }


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
    return get_daily_bars(ticker, days=days)


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
            headers=alpaca_headers(),
            timeout=15,
        )
        r.raise_for_status()
        positions = r.json() or []
        return sum(1 for p in positions if p.get("asset_class") == "us_option")
    except Exception as e:
        print(f"  Pozycje Alpaca error: {e}")
        return 0


def get_option_contracts(underlying: str, opt_type: str,
                          strike_min: float, strike_max: float,
                          expiry_min: str, expiry_max: str) -> list[dict]:
    """Fetch matching contracts from Alpaca /v2/options/contracts (free)."""
    try:
        r = requests.get(
            f"{ALPACA_BASE_URL}/v2/options/contracts",
            headers=alpaca_headers(),
            params={
                "underlying_symbol":   underlying,
                "type":                opt_type,
                "expiration_date_gte": expiry_min,
                "expiration_date_lte": expiry_max,
                "strike_price_gte":    round(strike_min, 2),
                "strike_price_lte":    round(strike_max, 2),
                "status":              "active",
                "limit":               100,
            },
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("option_contracts", []) or []
    except Exception as e:
        print(f"  Option chain {underlying}/{opt_type} error: {e}")
        return []


def pick_best_contract(contracts: list[dict], spot: float, max_premium: float):
    """
    Pick the contract closest to ATM whose latest premium is positive and fits
    the per-contract budget. Returns (contract_dict, premium) or None.
    """
    valid = []
    for c in contracts:
        try:
            premium = float(c.get("close_price") or 0)
            strike  = float(c.get("strike_price"))
        except (TypeError, ValueError):
            continue
        if premium <= 0 or premium > max_premium:
            continue
        valid.append((c, premium, strike))
    if not valid:
        return None
    valid.sort(key=lambda v: abs(v[2] - spot))
    contract, premium, _ = valid[0]
    return contract, premium


def place_options_bracket(contract_symbol: str, qty: int, premium: float,
                           tp_mult: float, sl_mult: float) -> dict | None:
    """Place a buy_to_open bracket order on the contract via Alpaca REST."""
    tp_limit = round(premium * tp_mult, 2)
    sl_stop  = round(premium * sl_mult, 2)
    payload = {
        "symbol":        contract_symbol,
        "qty":           str(qty),
        "side":          "buy",
        "type":          "limit",
        "limit_price":   str(round(premium, 2)),
        "time_in_force": "day",
        "order_class":   "bracket",
        "take_profit":   {"limit_price": str(tp_limit)},
        "stop_loss":     {"stop_price":  str(sl_stop)},
    }
    try:
        r = requests.post(
            f"{ALPACA_BASE_URL}/v2/orders",
            headers=alpaca_headers(),
            json=payload,
            timeout=15,
        )
        if r.status_code in (200, 201):
            return r.json()
        print(f"  Order error {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        print(f"  Order exception: {e}")
        return None


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
        "requires_approval": not AUTO_EXECUTE,
    }


def execute_proposal(proposal: dict) -> tuple[str, dict | None]:
    """
    Resolve a contract from the proposal window and place a bracket buy_to_open
    order via Alpaca REST.

    Returns (status, order):
      - ("executed", order_dict)  on success
      - ("no_contract", None)     when chain empty or no fit (silent skip)
      - ("rejected", None)        when Alpaca rejected the order
    """
    sym         = proposal["symbol"]
    opt_type    = proposal["option_type"]
    spot        = float(proposal["spot"])
    strike_min  = float(proposal["strike_min"])
    strike_max  = float(proposal["strike_max"])
    expiry_min  = proposal["expiry_min"]
    expiry_max  = proposal["expiry_max"]
    size_usd    = float(proposal["size_usd"])
    qty         = 1
    max_premium = size_usd / 100  # 1 contract = 100 shares

    contracts = get_option_contracts(sym, opt_type, strike_min, strike_max,
                                     expiry_min, expiry_max)
    if not contracts:
        print(f"  {sym}: brak kontraktów w oknie strike/expiry")
        return "no_contract", None

    pick = pick_best_contract(contracts, spot, max_premium)
    if not pick:
        print(f"  {sym}: brak kontraktu w budżecie ${max_premium:.2f}/share")
        return "no_contract", None

    contract, premium = pick
    contract_symbol   = contract["symbol"]
    print(f"  {sym}: wybrany {contract_symbol} strike={contract['strike_price']} "
          f"expiry={contract['expiration_date']} premium=${premium:.2f}")

    order = place_options_bracket(
        contract_symbol = contract_symbol,
        qty             = qty,
        premium         = premium,
        tp_mult         = TP_PREMIUM_MULT,
        sl_mult         = SL_PREMIUM_MULT,
    )
    if order:
        print(f"  Order placed: id={order.get('id')} status={order.get('status')}")
        return "executed", order
    return "rejected", None


def send_proposal(proposal: dict) -> bool:
    """Legacy routine path: forwards proposal to Cloudflare Worker -> Routine."""
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
    mode = "AUTO-EXECUTE (Alpaca REST)" if AUTO_EXECUTE else "ROUTINE (Cloudflare Worker)"
    print(f"\n[{now}] === OPTIONS MONITOR — {mode} ===")

    if not FINNHUB_API_KEY:
        print("BŁĄD: brak FINNHUB_API_KEY")
        sys.exit(1)
    if AUTO_EXECUTE and (not ALPACA_API_KEY or not ALPACA_SECRET_KEY):
        print("BŁĄD: AUTO_EXECUTE wymaga ALPACA_API_KEY + ALPACA_SECRET_KEY")
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
    proposals.sort(key=lambda p: p["rsi"], reverse=True)
    cap        = min(slots_left, MAX_PROPOSALS_PER_RUN)
    sent       = 0
    attempts   = 0
    skipped    = 0

    for proposal in proposals:
        if sent >= cap:
            break
        attempts += 1
        if AUTO_EXECUTE:
            status, order = execute_proposal(proposal)
            if status == "executed":
                sent += 1
                qty   = float(order.get("qty", 1))
                price = float(order.get("limit_price") or proposal["spot"])
                tp = sl = 0.0
                for leg in order.get("legs", []) or []:
                    if leg.get("side") == "sell" and leg.get("type") == "limit":
                        tp = float(leg.get("limit_price") or 0)
                    elif leg.get("side") == "sell" and leg.get("type") == "stop":
                        sl = float(leg.get("stop_price") or 0)
                notify_order_executed(
                    symbol   = order.get("symbol", proposal["symbol"]),
                    side     = proposal["action"],
                    qty      = qty,
                    price    = price,
                    size_usd = qty * price * 100,
                    sl       = sl,
                    tp       = tp,
                    strategy = "options-momentum",
                    order_id = order.get("id", ""),
                )
            elif status == "rejected":
                # Alpaca actually saw it and said no — worth notifying
                notify_signal(proposal, False)
            else:
                # "no_contract": silently keep iterating to the next proposal
                skipped += 1
        else:
            ok = send_proposal(proposal)
            if ok:
                sent += 1
            notify_signal(proposal, ok)
        if sent < cap and attempts < len(proposals):
            time.sleep(2)

    not_tried = max(0, len(proposals) - attempts)
    if skipped:
        print(f"  Pominieto {skipped} propozycji bez fitting kontraktu")
    if not_tried:
        print(f"  Nie tknieto {not_tried} propozycji (cap={cap}/run osiagniety)")

    notify_summary("Options Monitor", len(proposals), sent)
    print(f"[{now}] Wykonano: {sent}/{cap} (znaleziono {len(proposals)}, prób {attempts})\n")


if __name__ == "__main__":
    run_scan()
