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

# v3.22.0 — observability-only wiring into the canonical signal pipeline.
# emit_monitor_signal NEVER places trades; it forwards a SignalEvent to
# shared.signal_emitter.emit_signal_opportunity which persists via the
# opportunity ledger. NEVER imports alpaca_orders. NEVER calls the broker.
try:
    from monitor_signal_helper import emit_monitor_signal  # type: ignore
except Exception:
    try:
        from shared.monitor_signal_helper import emit_monitor_signal  # type: ignore
    except Exception:
        def emit_monitor_signal(*_a, **_kw):  # type: ignore
            return None

# v3.24 — monitor runtime diagnostics (ETAP 9). Fail-soft.
try:
    from monitor_runtime_diag import (  # type: ignore
        record_diag as _diag,
        DIAG_RAN, DIAG_INPUT_EMPTY, DIAG_NO_SIGNAL,
        DIAG_SIGNAL_DETECTED, DIAG_EMIT_ATTEMPTED,
        DIAG_EMIT_SUCCESS, DIAG_EMIT_FAILED,
    )
except Exception:
    try:
        from shared.monitor_runtime_diag import (  # type: ignore
            record_diag as _diag,
            DIAG_RAN, DIAG_INPUT_EMPTY, DIAG_NO_SIGNAL,
            DIAG_SIGNAL_DETECTED, DIAG_EMIT_ATTEMPTED,
            DIAG_EMIT_SUCCESS, DIAG_EMIT_FAILED,
        )
    except Exception:
        def _diag(*_a, **_kw):  # type: ignore
            return False
        DIAG_RAN = "RAN"; DIAG_INPUT_EMPTY = "INPUT_EMPTY"
        DIAG_NO_SIGNAL = "NO_SIGNAL"; DIAG_SIGNAL_DETECTED = "SIGNAL_DETECTED"
        DIAG_EMIT_ATTEMPTED = "EMIT_ATTEMPTED"
        DIAG_EMIT_SUCCESS = "EMIT_SUCCESS"; DIAG_EMIT_FAILED = "EMIT_FAILED"

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
    from notify import notify_signal, notify_summary, notify_order_executed
    from risk_guards import vix_guard
    from market_data import get_daily_bars
    from learning_state import load_strategy_state
    from runtime_config import options_enabled
    from portfolio_risk import evaluate_portfolio_risk
except ImportError:
    def notify_signal(*a, **k): pass
    def notify_summary(*a, **k): pass
    def notify_order_executed(*a, **k): pass
    def vix_guard(): return ("OK", 1.0)
    def get_daily_bars(symbol, days=35): return None
    def load_strategy_state(_): return {}
    def options_enabled(): return False
    def evaluate_portfolio_risk(*a, **k): return {"decision": "APPROVE", "failed": [], "warnings": [], "metrics": {}}


# ─── Options liquidity gate (spec §E.2) ──────────────────────────────────────
#
# Cheap deterministic checks BEFORE we POST an order. Free-tier-friendly:
# uses the same Alpaca options-snapshot we already fetch for limit pricing.

OPTIONS_SPREAD_PCT_MAX = float(os.environ.get("OPTIONS_SPREAD_PCT_MAX", "20.0"))
OPTIONS_MIN_OPEN_INTEREST = int(os.environ.get("OPTIONS_MIN_OPEN_INTEREST", "100"))
OPTIONS_MIN_VOLUME = int(os.environ.get("OPTIONS_MIN_VOLUME", "10"))


def check_options_liquidity(contract: dict, quote: dict | None) -> tuple[bool, list[str]]:
    """
    Returns (ok, reasons). Hard fail when bid<=0 / ask<=0 (illiquid) or
    spread too wide; soft warn (no fail) when OI/volume missing because
    Alpaca free chain doesn't always populate them.
    """
    reasons: list[str] = []
    if not quote or quote.get("bid", 0) <= 0 or quote.get("ask", 0) <= 0:
        reasons.append("no bid/ask quote")
        return False, reasons
    bid = float(quote["bid"])
    ask = float(quote["ask"])
    if ask <= bid:
        reasons.append(f"ask {ask} <= bid {bid} (crossed/locked)")
        return False, reasons
    mid = (bid + ask) / 2.0
    spread_pct = (ask - bid) / mid * 100.0
    if spread_pct > OPTIONS_SPREAD_PCT_MAX:
        reasons.append(f"spread {spread_pct:.1f}% > {OPTIONS_SPREAD_PCT_MAX}% max")
        return False, reasons
    if mid <= 0:
        reasons.append("mid premium <= 0")
        return False, reasons
    # OI / volume are best-effort — Alpaca free chain often omits them.
    oi = contract.get("open_interest") if isinstance(contract, dict) else None
    vol = contract.get("volume") if isinstance(contract, dict) else None
    try:
        if oi is not None and int(oi) < OPTIONS_MIN_OPEN_INTEREST:
            reasons.append(f"open_interest {oi} < {OPTIONS_MIN_OPEN_INTEREST}")
            return False, reasons
    except (TypeError, ValueError):
        pass
    try:
        if vol is not None and int(vol) < OPTIONS_MIN_VOLUME:
            reasons.append(f"volume {vol} < {OPTIONS_MIN_VOLUME}")
            return False, reasons
    except (TypeError, ValueError):
        pass
    return True, reasons

# ─── Konfiguracja ────────────────────────────────────────────────────────────

ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"
ALPACA_DATA_URL   = "https://data.alpaca.markets"   # for /options/snapshots
FINNHUB_API_KEY   = os.environ.get("FINNHUB_API_KEY", "")
CLOUDFLARE_WORKER_URL = os.environ.get("CLOUDFLARE_OPTIONS_WORKER_URL", "")
AUTO_EXECUTE      = os.environ.get("AUTO_EXECUTE_OPTIONS", "true").lower() == "true"

# Whitelist — same liquid names the equity monitors already watch
TICKERS = [
    "AAPL", "MSFT", "GOOGL", "NVDA", "META", "AMZN", "TSLA",
    "SPY", "QQQ", "JPM", "RTX", "LMT",
]

# Strategy parameters (strategies/options-strategy.md)
# v2.0 risk-on (was 500 / 2 / 3 / 1 / 14-21 / 35 / 45 / 1.80 / 0.50 / 3.0)
SIZE_USD                 = 2500    # USD per signal (5× v1)
MAX_CONTRACTS_PER_SIGNAL = 5       # was 2
MAX_OPEN_OPTIONS         = 10      # was 3 (3.3×)
MAX_PROPOSALS_PER_RUN    = 3       # was 1 (rate-limit no longer a problem in AUTO_EXECUTE)
DTE_MIN                  = 7       # was 14
DTE_MAX                  = 30      # was 21 (wider window)
IV_MAX_CALL_PCT          = 55.0    # was 35
IV_MAX_PUT_PCT           = 65.0    # was 45
RSI_CALL_MIN             = 45
RSI_CALL_MAX             = 65
RSI_PUT_MIN              = 72
TP_PREMIUM_MULT          = 2.20    # +120% (was +80%)
SL_PREMIUM_MULT          = 0.35    # -65%  (was -50%)
STRIKE_OTM_MAX_PCT       = 7.0     # ATM ±7% (was ±3%)
EARNINGS_BUFFER_DAYS     = 1       # iron rule, unchanged

# v3.8.6 (2026-05-16): P2 LLM-proposed regime gate + side concentration cap.
# Regime gate (#8): block PUT proposals when SPY RSI > 75 AND SPY 5d > +2%.
# Mean-reversion on PUT assumes overbought reverses; in strong uptrend it
# becomes systematic fade-the-trend (cost ~$3,120 on 2026-05-14 incident).
PUT_TREND_BLOCK_RSI       = 75.0
PUT_TREND_BLOCK_5D_PCT    = 0.02
# Symmetric: block CALL on capitulation (SPY RSI < 25 + 5d < -2%).
CALL_TREND_BLOCK_RSI      = 25.0
CALL_TREND_BLOCK_5D_PCT   = -0.02

# Side concentration cap (#9): max 5 PUTs OR 5 CALLs simultaneously,
# independent of MAX_OPEN_OPTIONS=10 (which is the union). Prevents the
# 2026-05-12 scenario of 15 open PUTs wiped in a single SPY rally.
PUT_CAP                   = 5
CALL_CAP                  = 5


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

def _fetch_account_snapshot() -> dict | None:
    """Helper for portfolio_risk gate. Returns Alpaca /v2/account dict or None."""
    if not ALPACA_API_KEY:
        return None
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/v2/account", headers=alpaca_headers(), timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"  account snapshot error: {e}")
    return None


def _fetch_positions_snapshot() -> list[dict]:
    """Helper for portfolio_risk gate. Returns Alpaca /v2/positions list."""
    if not ALPACA_API_KEY:
        return []
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/v2/positions", headers=alpaca_headers(), timeout=10)
        if r.status_code == 200:
            return r.json() or []
    except Exception as e:
        print(f"  positions snapshot error: {e}")
    return []


def _fetch_open_orders_snapshot() -> list[dict]:
    """Helper for portfolio_risk gate. Returns Alpaca /v2/orders?status=open list."""
    if not ALPACA_API_KEY:
        return []
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/v2/orders",
                         headers=alpaca_headers(), params={"status": "open"}, timeout=10)
        if r.status_code == 200:
            return r.json() or []
    except Exception as e:
        print(f"  open orders snapshot error: {e}")
    return []


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


def _get_option_quote(contract_symbol: str) -> dict | None:
    """
    Fetch latest bid/ask snapshot for an OCC option symbol.

    Returns {"bid": float, "ask": float, "mid": float} on success,
    None on any failure (caller falls back to close-price-based limit).
    """
    try:
        r = requests.get(
            f"{ALPACA_DATA_URL}/v1beta1/options/snapshots/{contract_symbol}",
            headers=alpaca_headers(),
            timeout=8,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        # snapshot shape: {"snapshot": {"latestQuote": {"bp": bid, "ap": ask, ...}}}
        snap = (data.get("snapshot") or data)
        quote = (snap.get("latestQuote") or snap.get("latest_quote") or {})
        bid = float(quote.get("bp") or quote.get("bid_price") or 0)
        ask = float(quote.get("ap") or quote.get("ask_price") or 0)
        if bid <= 0 or ask <= 0 or ask < bid:
            return None
        return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2.0}
    except Exception as e:
        print(f"  options quote {contract_symbol} error: {e}")
        return None


def _compute_buy_limit_price(contract_symbol: str, close_premium: float) -> tuple[float, str]:
    """
    Compute aggressive buy limit_price using bid/ask midpoint when available.

    Per LLM proposal 2026-05-09 (40% fill rate root cause): close-price-based
    limit (`close * 1.05`) systematically lands BELOW market mid because
    options spreads run 5-15% wide. Pricing at midpoint + 5% margin should
    push fill rate from ~40% to 70%+.

    Returns (limit_price, source) where source explains which formula won
    so monitor logs make the choice visible.
    """
    quote = _get_option_quote(contract_symbol)
    if quote and quote["mid"] > 0:
        # Aggressive buyer: pay 5% over midpoint to clear typical spreads
        lim = round(quote["mid"] * 1.05, 2)
        return lim, f"mid-aggressive (bid={quote['bid']}, ask={quote['ask']}, mid={quote['mid']:.2f})"
    # Fallback when snapshot unavailable: 20% over close (was 5% — still
    # too tight for typical options spreads, but no quote means we're
    # flying blind anyway).
    lim = round(close_premium * 1.20, 2)
    return lim, f"close-fallback (close={close_premium}, *1.20 = {lim})"


def place_options_buy(contract_symbol: str, qty: int, premium: float) -> dict | None:
    """
    Place a SIMPLE limit buy_to_open order via Alpaca REST.

    Note: Alpaca paper does NOT support `order_class=bracket` for options
    (returns 422 'complex orders not supported for options trading').
    TP/SL must be placed as separate orders after the fill — handled by a
    follow-up exit step (or manually by the user via the dashboard).

    Limit price is computed via _compute_buy_limit_price using bid/ask
    midpoint + 5% margin (fallback close*1.20 when no quote available).
    Replaces the prior `close * 1.05` which gave us ~40% fill rate over
    multiple sessions.
    """
    # Tag with strategy-prefixed client_order_id so the learning-loop
    # analyzer can attribute fills to "options-momentum" instead of
    # falling back on Alpaca's UUID auto-generation. Format mirrors
    # shared/alpaca_orders.py::_client_order_id.
    ts = datetime.now(timezone.utc).strftime("%H%M%S%f")[:-3]
    safe_sym = contract_symbol.replace("/", "").replace(" ", "")
    client_order_id = f"options-momentum-{safe_sym}-{ts}"

    limit_price, src = _compute_buy_limit_price(contract_symbol, premium)
    print(f"  limit_price ${limit_price} via {src}")

    payload = {
        "symbol":          contract_symbol,
        "qty":             str(qty),
        "side":            "buy",
        "type":            "limit",
        "limit_price":     str(limit_price),
        "time_in_force":   "day",
        "client_order_id": client_order_id,
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


# ─── SPY regime helper (v3.8.6 — for regime gate + LLM context) ─────────────

def _get_spy_regime() -> tuple[float | None, float | None]:
    """
    Returns (spy_rsi_14, spy_5d_return_decimal) or (None, None) on failure.
    Used by PUT/CALL regime gate. Fetches 10 daily bars via Alpaca data
    API and computes RSI + 5d total return.
    """
    try:
        bars = get_candles("SPY")
    except Exception:
        return (None, None)
    if not bars or not bars.get("close") or len(bars["close"]) < 6:
        return (None, None)
    closes = bars["close"]
    spy_rsi = calculate_rsi(closes)
    try:
        prev = closes[-6]
        curr = closes[-1]
        spy_5d = (curr / prev - 1) if prev > 0 else None
    except Exception:
        spy_5d = None
    return (spy_rsi, spy_5d)


def _count_open_options_by_side() -> tuple[int, int]:
    """
    Returns (open_put_count, open_call_count) across all underlying
    symbols. Used by PUT_CAP/CALL_CAP side concentration gate.
    Fail-soft: returns (0, 0) on Alpaca error so monitor doesn't freeze.
    """
    try:
        r = requests.get(
            f"{ALPACA_BASE_URL}/v2/positions",
            headers=alpaca_headers(),
            timeout=10,
        )
        if r.status_code != 200:
            return (0, 0)
        positions = r.json() or []
    except Exception:
        return (0, 0)
    puts = 0
    calls = 0
    for p in positions:
        if p.get("asset_class") != "us_option":
            continue
        sym = p.get("symbol", "")
        # OCC option symbol: <root><YYMMDD><C|P><strike8>
        # The C/P character is at position len-9.
        if len(sym) < 15:
            continue
        side_char = sym[-9].upper()
        if side_char == "P":
            puts += 1
        elif side_char == "C":
            calls += 1
    return (puts, calls)


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

    # v3.8.6 (2026-05-16) — regime gate (LLM proposal 2026-05-13). PUT
    # mean-reversion assumes overbought reverses; in strong uptrend
    # (SPY RSI > 75 AND SPY 5d > +2%) it becomes systematic fade-the-trend.
    # 2026-05-14 cost: ~$3,120 from PUTs fading SPY rally. Symmetric for CALL.
    if opt_type in ("put", "call"):
        spy_rsi, spy_5d_pct = _get_spy_regime()
        if spy_rsi is not None and spy_5d_pct is not None:
            if opt_type == "put" and spy_rsi > PUT_TREND_BLOCK_RSI and spy_5d_pct > PUT_TREND_BLOCK_5D_PCT:
                print(f"  {ticker}: REGIME GATE — SPY RSI={spy_rsi:.1f} (>{PUT_TREND_BLOCK_RSI}) "
                      f"+ 5d={spy_5d_pct*100:+.1f}% (>+{PUT_TREND_BLOCK_5D_PCT*100:.0f}%) "
                      f"→ PUT blocked (fade-the-trend protection)")
                return None
            if opt_type == "call" and spy_rsi < CALL_TREND_BLOCK_RSI and spy_5d_pct < CALL_TREND_BLOCK_5D_PCT:
                print(f"  {ticker}: REGIME GATE — SPY RSI={spy_rsi:.1f} (<{CALL_TREND_BLOCK_RSI}) "
                      f"+ 5d={spy_5d_pct*100:+.1f}% (<{CALL_TREND_BLOCK_5D_PCT*100:.0f}%) "
                      f"→ CALL blocked (fade-the-capitulation protection)")
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
        # Autonomy contract: there is no human-approval step. False here
        # means the system auto-executes; True means it auto-rejects (and
        # logs an audit email). Either way, the operator is never asked.
        "autonomous_decision": True,
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

    # Liquidity gate (spec §E.2)
    quote = _get_option_quote(contract_symbol)
    ok_liq, liq_reasons = check_options_liquidity(contract, quote)
    if not ok_liq:
        print(f"  {sym}: liquidity reject — {'; '.join(liq_reasons)}")
        return "rejected", None

    # Portfolio-level risk gate (spec §D) — fail-open if Alpaca unavailable.
    try:
        from portfolio_risk import evaluate_portfolio_risk as _eval_port
        account_snap = _fetch_account_snapshot()
        positions_snap = _fetch_positions_snapshot()
        open_orders_snap = _fetch_open_orders_snapshot()
        port_verdict = _eval_port(
            proposed_trade = {
                "symbol":     contract_symbol,
                "side":       "buy_to_open",
                "size_usd":   qty * premium * 100,
                "asset_class": "us_option",
            },
            account = account_snap,
            positions = positions_snap,
            open_orders = open_orders_snap,
        )
        if port_verdict["decision"] == "REJECT":
            print(f"  {sym}: portfolio-risk REJECT — {'; '.join(port_verdict['failed'])}")
            return "rejected", None
        for w in port_verdict.get("warnings", []):
            print(f"  portfolio-risk warn: {w}")
    except Exception as e:  # pragma: no cover — fail-open
        print(f"  portfolio-risk unavailable ({type(e).__name__}: {e}); proceeding")

    # v3.14.0 (2026-06-02) — confidence gate (closes CONF-002).
    # Options doesn't use shared.place_simple_buy; gate inline before broker.
    try:
        from confidence_builder import build_confidence_inputs as _build_ci
        from confidence import compute_confidence as _compute_conf
        # Normalize RSI to primary_score:
        # CALL setup: RSI 45-65 (sweet spot ~55) → 0.5 baseline
        # PUT setup:  RSI > 72 (extreme) → strong primary_score
        rsi = float(proposal.get("rsi") or 50.0)
        if opt_type == "PUT":
            primary = max(0.0, min(1.0, (rsi - 65.0) / 20.0))  # RSI 65→0, 85→1
        else:
            primary = max(0.0, min(1.0, 1.0 - abs(rsi - 55.0) / 20.0))  # peak at 55
        ci = _build_ci(
            strategy      = "options-momentum",
            primary_score = primary,
            regime        = "NEUTRAL",
            bars_count    = 60,
        )
        _report = _compute_conf(**ci)
        if _report.decision == "BLOCK":
            print(f"  {sym}: confidence BLOCK total={_report.total:.3f} — skip")
            return "rejected", None
        if _report.decision == "ALERT_ONLY":
            print(f"  {sym}: confidence ALERT_ONLY {_report.total:.3f} — proceeding")
    except Exception as _ci_e:
        print(f"  confidence gate skipped (non-fatal): {type(_ci_e).__name__}")

    order = place_options_buy(
        contract_symbol = contract_symbol,
        qty             = qty,
        premium         = premium,
    )
    if order:
        print(f"  Order placed: id={order.get('id')} status={order.get('status')}")
        # Stash intended TP/SL on the order dict so the email shows them
        order["_tp_target"] = round(premium * TP_PREMIUM_MULT, 2)
        order["_sl_target"] = round(premium * SL_PREMIUM_MULT, 2)
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
    _diag("options-monitor", DIAG_RAN, {"mode": mode})

    # Global kill switch — OPTIONS_ENABLED must be true to allow ANY options
    # entry. Defaults to false per spec §E.1. Existing/exit positions are
    # NOT affected — options-exit-monitor still runs independently to close
    # what's already open.
    if not options_enabled():
        print("  OPTIONS_ENABLED=false (default) -> safe no-op")
        print("  To enable, set env OPTIONS_ENABLED=true in the workflow YAML.")
        notify_summary("Options Monitor", 0, 0)
        return

    if not FINNHUB_API_KEY:
        print("BŁĄD: brak FINNHUB_API_KEY")
        sys.exit(1)
    if AUTO_EXECUTE and (not ALPACA_API_KEY or not ALPACA_SECRET_KEY):
        print("BŁĄD: AUTO_EXECUTE wymaga ALPACA_API_KEY + ALPACA_SECRET_KEY")
        sys.exit(1)

    # Learning loop adaptations (read learning-loop/state.json)
    learning = load_strategy_state("options-momentum")
    if not learning.get("enabled", True):
        paused = learning.get("paused_until", "?")
        print(f"  Learning loop: options-momentum DISABLED (paused_until={paused})")
        print(f"  Rationale: {learning.get('rationale', '')}")
        notify_summary("Options Monitor", 0, 0)
        return
    learning_mult = float(learning.get("size_multiplier", 1.0))
    learning_bias = learning.get("side_bias")  # "long" | "short" | None
    if learning and (abs(learning_mult - 1.0) > 0.01 or learning_bias):
        print(f"  Learning loop: size_multiplier={learning_mult:.2f}, side_bias={learning_bias or 'none'}")
        print(f"  Rationale: {learning.get('rationale', '')}")

    vix_status, size_mult = vix_guard()
    if vix_status == "HALT":
        notify_summary("Options Monitor", 0, 0)
        return

    # Combine VIX size_mult with learning size_multiplier
    combined_size_mult = size_mult * learning_mult

    open_count = count_open_options()
    if open_count >= MAX_OPEN_OPTIONS:
        print(f"  Otwartych opcji: {open_count}/{MAX_OPEN_OPTIONS} -> brak miejsca, pomijam skan")
        notify_summary("Options Monitor", 0, 0)
        return
    slots_left = MAX_OPEN_OPTIONS - open_count
    print(f"  Otwartych opcji: {open_count}/{MAX_OPEN_OPTIONS} (slotów: {slots_left})")

    # v3.8.6 — side concentration cap (LLM proposal 2026-05-13). PUT/CALL
    # are counted independently of MAX_OPEN_OPTIONS=10. Prevents single
    # SPY rally from wiping a full-PUT portfolio (2026-05-12 incident).
    open_puts, open_calls = _count_open_options_by_side()
    print(f"  Side breakdown: {open_puts} PUTs (cap {PUT_CAP}), {open_calls} CALLs (cap {CALL_CAP})")

    proposals = []
    skipped_by_bias = 0
    skipped_by_side_cap = 0
    for ticker in TICKERS:
        proposal = build_proposal(ticker)
        if proposal:
            # Learning side_bias filter: skip CALL when bias=short, skip PUT when bias=long
            if learning_bias == "short" and proposal.get("option_type") == "call":
                skipped_by_bias += 1
                continue
            if learning_bias == "long" and proposal.get("option_type") == "put":
                skipped_by_bias += 1
                continue
            # Side concentration cap — skip if proposed side already at cap.
            opt_type = proposal.get("option_type")
            if opt_type == "put" and open_puts >= PUT_CAP:
                print(f"  {ticker}: SIDE CAP — {open_puts} open PUTs ≥ {PUT_CAP}, skip")
                skipped_by_side_cap += 1
                continue
            if opt_type == "call" and open_calls >= CALL_CAP:
                print(f"  {ticker}: SIDE CAP — {open_calls} open CALLs ≥ {CALL_CAP}, skip")
                skipped_by_side_cap += 1
                continue
            proposal["size_usd"] = round(proposal["size_usd"] * combined_size_mult)
            proposals.append(proposal)
        time.sleep(0.5)

    if skipped_by_bias:
        print(f"  Learning side_bias '{learning_bias}': pominieto {skipped_by_bias} propozycji o przeciwnym kierunku")

    print(f"  Znalezione propozycje: {len(proposals)}")
    if not proposals:
        _diag("options-monitor", DIAG_NO_SIGNAL,
              {"open_options": open_count,
               "skipped_by_bias": skipped_by_bias,
               "skipped_by_side_cap": skipped_by_side_cap})
    else:
        _diag("options-monitor", DIAG_SIGNAL_DETECTED,
              {"proposals": len(proposals)})
    proposals.sort(key=lambda p: p["rsi"], reverse=True)
    cap        = min(slots_left, MAX_PROPOSALS_PER_RUN)
    sent       = 0
    attempts   = 0
    skipped    = 0

    for proposal in proposals:
        if sent >= cap:
            break
        attempts += 1
        _diag("options-monitor", DIAG_EMIT_ATTEMPTED,
              {"symbol": proposal.get("symbol"),
               "action": proposal.get("action")})
        # v3.22.0 — observability emit BEFORE execute_proposal so the
        # opportunity ledger captures intent even if the broker rejects.
        # NEVER places a trade.
        try:
            emit_monitor_signal(
                source_monitor="options-monitor",
                strategy_id="options-momentum",
                symbol=proposal.get("symbol", "?"),
                asset_class="us_option",
                side=("long" if str(proposal.get("action", "")).upper() == "CALL"
                      else "short"),
                action=proposal.get("action", "CALL"),
                entry_capable=True,
                raw_signal={
                    "rsi":    proposal.get("rsi"),
                    "spot":   proposal.get("spot"),
                    "score":  proposal.get("score"),
                    "expiry": proposal.get("expiry"),
                },
                confidence_inputs={
                    "primary_score": float(proposal.get("score", 0.6)),
                    "regime":        proposal.get("regime"),
                },
                risk_inputs={"size_usd": proposal.get("size_usd", 500)},
                metadata={"audit_link":
                          f"options-{proposal.get('symbol', '?')}-"
                          f"{proposal.get('action', 'CALL')}"},
            )
        except Exception:
            pass
        if AUTO_EXECUTE:
            status, order = execute_proposal(proposal)
            if status == "executed":
                sent += 1
                _diag("options-monitor", DIAG_EMIT_SUCCESS,
                      {"symbol": proposal.get("symbol")})
                qty   = float(order.get("qty", 1))
                price = float(order.get("limit_price") or proposal["spot"])
                tp    = float(order.get("_tp_target", 0))
                sl    = float(order.get("_sl_target", 0))
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
                _diag("options-monitor", DIAG_EMIT_FAILED,
                      {"symbol": proposal.get("symbol"),
                       "reason": "alpaca_rejected"})
                # Alpaca actually saw it and said no — worth notifying
                notify_signal(proposal, False)
            else:
                _diag("options-monitor", DIAG_EMIT_FAILED,
                      {"symbol": proposal.get("symbol"),
                       "reason": "no_contract"})
                # "no_contract": silently keep iterating to the next proposal
                skipped += 1
        else:
            ok = send_proposal(proposal)
            if ok:
                sent += 1
                _diag("options-monitor", DIAG_EMIT_SUCCESS,
                      {"symbol": proposal.get("symbol"),
                       "path": "routine"})
            else:
                _diag("options-monitor", DIAG_EMIT_FAILED,
                      {"symbol": proposal.get("symbol"),
                       "path": "routine"})
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
    # v3.14.0 (2026-06-02) — heartbeat ping (closes ARCH-001/RUNTIME-002/CONF-003).
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "shared"))
        from heartbeat import ping as _hb_ping
        _hb_ping("options-monitor", status="ok")
    except Exception as _hb_e:
        print(f"  heartbeat ping failed (non-fatal): {type(_hb_e).__name__}")
