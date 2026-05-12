"""
Crypto Monitor — 24/7 predator-grade crypto scanner

v2.4 (2026-05-12): EXPANDED UNIVERSE + per-tier sizing/TP/SL.

Tier 1 (proven majors): BTC, ETH — full v2.0 size, standard TP/SL.
Tier 2 (mid-cap alt): SOL, AVAX, LINK, DOT, MATIC, LTC, BCH, UNI, AAVE —
   smaller size, TIGHTER TP (+10%) / wider SL (-8%) for quick wins on
   shorter timeframes. Smaller liquidity = wider spread = needs higher
   conviction filter (volume 3× avg, BTC dominance guard).

Scans 1h timeframe every 30 min via Alpaca v1beta3 crypto endpoint.
After candidate signals collected, optional LLM Curator (analog to
reddit-monitor) validates the predator setup and selects 0-3 emits.
"""

import os
import sys
import requests
from datetime import datetime, timezone, timedelta

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
    from notify import notify_signal, notify_summary
    from risk_guards import vix_guard, has_open_position, daily_drawdown_guard, get_account_status, concentration_ok, get_open_positions
    from alpaca_orders import execute_crypto_signal
except ImportError:
    def notify_signal(*a, **k): pass
    def notify_summary(*a, **k): pass
    def vix_guard(): return ("OK", 1.0)
    def has_open_position(_): return False
    def daily_drawdown_guard(account=None): return ("OK", "stub")
    def get_account_status(): return None
    def concentration_ok(_s, _n, equity=None): return (True, 0.0)
    def get_open_positions(): return []
    def execute_crypto_signal(_s): return None

# Default: AUTO_EXECUTE via Alpaca REST. USE_ROUTINE=true -> legacy worker path.
USE_ROUTINE = os.environ.get("USE_ROUTINE", "false").lower() == "true"

# ─── Konfiguracja ────────────────────────────────────────────────────────────

ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_DATA_URL   = "https://data.alpaca.markets"

CLOUDFLARE_WORKER_URL = os.environ.get("CLOUDFLARE_CRYPTO_WORKER_URL", "")

# ─── Coin tiers (predator strategy 2026-05-12) ────────────────────────────────
#
# Each coin gets per-tier params. Tier 1 = proven, Tier 2 = mid-cap alts
# (quick-win mode: tighter TP, wider SL, higher conviction threshold).
#
# size_long/short:   USD per entry
# tp_pct:            take profit % of entry (positive for both sides)
# sl_pct:            stop loss % of entry  (positive number; direction handled
#                                          by side: long → 1 - sl, short → 1 + sl)
# vol_mult:          volume vs 20-bar avg multiplier required for entry
# rsi_long_max:      upper RSI bound for long entries (we want momentum not
#                    exhaustion — small caps overbought = pump-in-progress = trap)
COIN_TIERS = {
    # ─── Tier 1 — proven majors (full size, standard TP/SL) ─────────────
    "BTC/USD":   {"tier": 1, "size_long": 8000, "size_short": 6000,
                  "tp_pct": 0.20, "sl_pct": 0.07, "vol_mult": 2.0,
                  "rsi_long_max": 68},
    "ETH/USD":   {"tier": 1, "size_long": 4000, "size_short": 3000,
                  "tp_pct": 0.20, "sl_pct": 0.07, "vol_mult": 2.0,
                  "rsi_long_max": 68},
    # ─── Tier 2 — mid-cap alts (quick wins, tighter TP, conviction filter) ──
    # $2.5k each; +10% TP / -8% SL = R:R ~1.25 (lower than Tier 1's ~2.9 but
    # much faster cycles = more chances per week).
    "SOL/USD":   {"tier": 2, "size_long": 2500, "size_short": 2000,
                  "tp_pct": 0.10, "sl_pct": 0.08, "vol_mult": 3.0,
                  "rsi_long_max": 65},
    "AVAX/USD":  {"tier": 2, "size_long": 2500, "size_short": 2000,
                  "tp_pct": 0.10, "sl_pct": 0.08, "vol_mult": 3.0,
                  "rsi_long_max": 65},
    "LINK/USD":  {"tier": 2, "size_long": 2500, "size_short": 2000,
                  "tp_pct": 0.10, "sl_pct": 0.08, "vol_mult": 3.0,
                  "rsi_long_max": 65},
    "DOT/USD":   {"tier": 2, "size_long": 2500, "size_short": 2000,
                  "tp_pct": 0.10, "sl_pct": 0.08, "vol_mult": 3.0,
                  "rsi_long_max": 65},
    "MATIC/USD": {"tier": 2, "size_long": 2500, "size_short": 2000,
                  "tp_pct": 0.10, "sl_pct": 0.08, "vol_mult": 3.0,
                  "rsi_long_max": 65},
    "LTC/USD":   {"tier": 2, "size_long": 2500, "size_short": 2000,
                  "tp_pct": 0.10, "sl_pct": 0.08, "vol_mult": 3.0,
                  "rsi_long_max": 65},
    "BCH/USD":   {"tier": 2, "size_long": 2500, "size_short": 2000,
                  "tp_pct": 0.10, "sl_pct": 0.08, "vol_mult": 3.0,
                  "rsi_long_max": 65},
    "UNI/USD":   {"tier": 2, "size_long": 2500, "size_short": 2000,
                  "tp_pct": 0.10, "sl_pct": 0.08, "vol_mult": 3.0,
                  "rsi_long_max": 65},
    "AAVE/USD":  {"tier": 2, "size_long": 2500, "size_short": 2000,
                  "tp_pct": 0.10, "sl_pct": 0.08, "vol_mult": 3.0,
                  "rsi_long_max": 65},
}
CRYPTO_SYMBOLS = list(COIN_TIERS.keys())

# Predator filters — applied AFTER per-coin technical signal
MOMENTUM_24H_MIN_PCT = 3.0    # coin must have moved >3% in 24h (active trend)
MOMENTUM_24H_MAX_PCT = 15.0   # but <15% (don't chase late-stage pump)
BTC_DOMINANCE_GUARD_PCT = -3.0  # if BTC drops >=3% in 1h → block alt longs
MAX_ALT_POSITIONS = 3         # cap simultaneous Tier 2 open positions

# Global circuit breakers
CRYPTO_MAX_EXPOSURE_USD = 25000   # v2.0 — combined cap

# Shared RSI thresholds
RSI_LONG_MIN  = 45
RSI_SHORT_MAX = 35

# ─── Alpaca Market Data API ───────────────────────────────────────────────────

def alpaca_data_get(endpoint: str, params: dict = None) -> dict:
    headers = {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }
    resp = requests.get(
        f"{ALPACA_DATA_URL}{endpoint}",
        headers=headers,
        params=params or {},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_crypto_bars(symbol: str, limit: int = 50) -> list[dict]:
    """
    Pobiera 1h świece dla symbolu crypto.
    Alpaca używa 'BTC/USD' w parametrach jako 'BTCUSD'.
    """
    # Pobierz 5 dni historii (120h świec 1h = wystarczy na RSI i 20-świecowe max/min)
    start = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        data = alpaca_data_get(
            "/v1beta3/crypto/us/bars",
            {
                "symbols":   symbol,   # BTC/USD — ze ukośnikiem
                "timeframe": "1Hour",
                "limit":     limit,
                "start":     start,
                "sort":      "asc",
            }
        )
        # Klucz w odpowiedzi może być "BTC/USD" lub "BTCUSD"
        alpaca_symbol_noslash = symbol.replace("/", "")
        bars_data = (
            data.get("bars", {}).get(symbol, [])
            or data.get("bars", {}).get(alpaca_symbol_noslash, [])
        )
        return bars_data
    except Exception as e:
        print(f"  {symbol} błąd pobierania bars: {e}")
        return []


# ─── Wskaźniki techniczne ─────────────────────────────────────────────────────

def calculate_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains  = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def is_weekend() -> bool:
    return datetime.now(timezone.utc).weekday() >= 5


# ─── BTC dominance guard (predator filter 2026-05-12) ────────────────────────

# Module-level cache for BTC 1h change so we don't fetch it 11× per run.
_btc_change_cache: dict = {"value": None, "ts": None}

def get_btc_1h_change_pct() -> float | None:
    """
    BTC % change over the last completed 1h candle.
    Used as a regime filter: if BTC crashes -3%+ in 1h, alt longs are
    typically lethal (correlated crash). Cached per-run.
    """
    cached_at = _btc_change_cache.get("ts")
    if cached_at and (datetime.now(timezone.utc) - cached_at).total_seconds() < 300:
        return _btc_change_cache["value"]
    bars = get_crypto_bars("BTC/USD", limit=3)
    if not bars or len(bars) < 2:
        return None
    try:
        prev_close = float(bars[-2]["c"])
        curr_close = float(bars[-1]["c"])
        pct = (curr_close - prev_close) / prev_close * 100 if prev_close > 0 else 0
        _btc_change_cache["value"] = pct
        _btc_change_cache["ts"] = datetime.now(timezone.utc)
        return pct
    except (KeyError, ValueError, ZeroDivisionError):
        return None


def calculate_24h_move_pct(closes: list[float]) -> float | None:
    """
    Percent move over the last 24 hours (24 × 1h bars).
    Used as predator filter: enter only when coin is ALREADY in a
    confirmed move (>3%) but BEFORE late-stage pump (<15% in 24h).
    """
    if len(closes) < 25:
        return None
    prev = closes[-25]
    curr = closes[-1]
    if prev <= 0:
        return None
    return (curr - prev) / prev * 100


# ─── Sygnały ─────────────────────────────────────────────────────────────────

def check_crypto_signal(symbol: str, btc_1h_change: float | None
                          ) -> dict | None:
    """
    Per-coin predator-style signal check on 1h timeframe.

    Filters (in order):
      1. Per-coin tier config (size, TP/SL pct, volume mult, rsi max)
      2. 1h breakout: price > 20-bar high (LONG) or < 20-bar low (SHORT)
      3. Volume spike: vol > tier.vol_mult × 20-bar avg
      4. RSI in band: long_min .. tier.rsi_long_max (long) | < RSI_SHORT_MAX (short)
      5. PREDATOR: 24h move in [MOMENTUM_24H_MIN_PCT, MOMENTUM_24H_MAX_PCT]
                   (skip stalls AND late-stage pumps)
      6. PREDATOR: for Tier 2 LONG entries, BTC 1h change > BTC_DOMINANCE_GUARD_PCT
                   (don't long an alt during BTC dump — correlated crash)

    Returns signal dict or None.
    """
    cfg = COIN_TIERS.get(symbol)
    if not cfg:
        return None
    tier = cfg["tier"]

    bars = get_crypto_bars(symbol, limit=50)
    if len(bars) < 25:
        print(f"  {symbol}: za mało danych ({len(bars)} świec)")
        return None

    closes  = [float(b["c"]) for b in bars]
    highs   = [float(b["h"]) for b in bars]
    lows    = [float(b["l"]) for b in bars]
    volumes = [float(b["v"]) for b in bars]

    current_price  = closes[-1]
    current_volume = volumes[-1]

    high_20  = max(highs[-21:-1])
    low_20   = min(lows[-21:-1])
    avg_vol  = sum(volumes[-21:-1]) / 20 if avg_vol_test_safe(volumes) else 1.0

    rsi = calculate_rsi(closes)
    move_24h = calculate_24h_move_pct(closes)

    vol_mult        = cfg["vol_mult"]
    tp_pct          = cfg["tp_pct"]
    sl_pct          = cfg["sl_pct"]
    rsi_long_max    = cfg["rsi_long_max"]

    # Common state for return
    common = {
        "symbol":         symbol,
        "price":          round(current_price, 2),
        "rsi":            round(rsi, 1) if rsi else None,
        "tier":           tier,
        "move_24h_pct":   round(move_24h, 2) if move_24h is not None else None,
        "btc_1h_change":  round(btc_1h_change, 2) if btc_1h_change is not None else None,
        "volume_ratio":   round(current_volume / avg_vol, 2) if avg_vol > 0 else None,
    }

    # ── PREDATOR FILTERS (apply BEFORE breakout check to short-circuit) ──
    if move_24h is not None and not (
        MOMENTUM_24H_MIN_PCT <= abs(move_24h) <= MOMENTUM_24H_MAX_PCT
    ):
        print(f"  {symbol}: move_24h={move_24h:+.2f}% poza zakresem "
              f"[{MOMENTUM_24H_MIN_PCT}%..{MOMENTUM_24H_MAX_PCT}%] — skip")
        return None

    # ── LONG entry ─────────────────────────────────────────────────────
    if (current_price > high_20
            and current_volume > avg_vol * vol_mult
            and rsi is not None and RSI_LONG_MIN <= rsi <= rsi_long_max):
        # Tier 2 alt-long: BTC dominance guard
        if tier == 2 and btc_1h_change is not None \
                and btc_1h_change <= BTC_DOMINANCE_GUARD_PCT:
            print(f"  {symbol}: BTC 1h={btc_1h_change:+.2f}% (<= {BTC_DOMINANCE_GUARD_PCT}%) "
                  f"— alt long BLOCKED (BTC crash)")
            return None
        stop_loss   = round(current_price * (1 - sl_pct), 4)
        take_profit = round(current_price * (1 + tp_pct), 4)
        print(f"  LONG {symbol} [T{tier}]: ${current_price:.2f} > high20=${high_20:.2f}, "
              f"RSI={rsi:.1f}, vol={common['volume_ratio']}x, 24h={common['move_24h_pct']}%")
        return {**common,
            "action":      "BUY",
            "strategy":    "crypto-momentum",
            "stop_loss":   stop_loss,
            "take_profit": take_profit,
            "size_usd":    cfg["size_long"],
        }

    # ── SHORT entry ────────────────────────────────────────────────────
    if (current_price < low_20
            and current_volume > avg_vol * max(1.5, vol_mult - 0.5)
            and rsi is not None and rsi < RSI_SHORT_MAX):
        stop_loss   = round(current_price * (1 + sl_pct), 4)
        take_profit = round(current_price * (1 - tp_pct), 4)
        print(f"  SHORT {symbol} [T{tier}]: ${current_price:.2f} < low20=${low_20:.2f}, "
              f"RSI={rsi:.1f}, vol={common['volume_ratio']}x, 24h={common['move_24h_pct']}%")
        return {**common,
            "action":      "SELL_SHORT",
            "strategy":    "crypto-breakdown",
            "stop_loss":   stop_loss,
            "take_profit": take_profit,
            "size_usd":    cfg["size_short"],
        }

    print(
        f"  {symbol} [T{tier}]: ${current_price:.2f} hi20=${high_20:.2f} lo20=${low_20:.2f} "
        f"RSI={f'{rsi:.1f}' if rsi else 'N/A'} vol={common['volume_ratio']}x "
        f"24h={common['move_24h_pct']}% — brak sygnału"
    )
    return None


def avg_vol_test_safe(volumes: list[float]) -> bool:
    """Defensive: ensure we have enough non-zero bars for avg."""
    nonzero = [v for v in volumes[-21:-1] if v > 0]
    return len(nonzero) >= 15


# ─── Wysyłanie alertu ────────────────────────────────────────────────────────

def send_alert(alert: dict) -> bool:
    """
    Default: AUTO_EXECUTE via Alpaca REST (simple limit; Alpaca crypto =
    no bracket support, exit-monitor handles SL/TP via crypto thresholds).
    USE_ROUTINE=true -> legacy worker path.
    """
    if not USE_ROUTINE:
        order = execute_crypto_signal(alert)
        if order:
            print(f"  Order {alert['action']} {alert['symbol']}: id={order.get('id')} qty={order.get('qty')} @ ${order.get('limit_price')}")
            return True
        print(f"  Order {alert['action']} {alert['symbol']}: REJECTED (Alpaca)")
        return False

    # Legacy routine path (opt-in)
    if not CLOUDFLARE_WORKER_URL:
        print(f"  BRAK CLOUDFLARE_CRYPTO_WORKER_URL — sygnał lokalnie: {alert}")
        return False
    try:
        resp = requests.post(
            CLOUDFLARE_WORKER_URL,
            json=alert,
            timeout=30,
        )
        print(f"  Routine forward {alert['action']} {alert['symbol']}: HTTP {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        print(f"  Błąd wysyłania alertu: {e}")
        return False


# ─── Główna logika ────────────────────────────────────────────────────────────

def _count_alt_open_positions() -> int:
    """Count current open Tier 2 (alt) crypto positions."""
    try:
        positions = get_open_positions()
    except Exception:
        return 0
    alt_symbols = {s for s, c in COIN_TIERS.items() if c["tier"] >= 2}
    # Alpaca crypto positions report symbol as "BTCUSD" (no slash)
    alt_noslash = {s.replace("/", "") for s in alt_symbols}
    return sum(1 for p in positions if p.get("symbol", "") in alt_noslash
               or p.get("symbol", "") in alt_symbols)


def run_scan():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n[{now_str}] === CRYPTO MONITOR (predator v2.4) ===")
    print(f"  Universe: {len(CRYPTO_SYMBOLS)} coins "
          f"(Tier1={sum(1 for c in COIN_TIERS.values() if c['tier']==1)}, "
          f"Tier2={sum(1 for c in COIN_TIERS.values() if c['tier']==2)})")

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("BŁĄD: Brak ALPACA_API_KEY lub ALPACA_SECRET_KEY")
        sys.exit(1)

    # v2.0 safety net: account-level circuit breaker BEFORE VIX guard
    account = get_account_status()
    dd_status, _ = daily_drawdown_guard(account=account)
    if dd_status == "HALT":
        notify_summary("Crypto Monitor", 0, 0)
        return

    vix_status, size_mult = vix_guard()
    if vix_status == "HALT":
        notify_summary("Crypto Monitor", 0, 0)
        return

    # BTC dominance reading once per run (used for alt-long block)
    btc_1h_change = get_btc_1h_change_pct()
    if btc_1h_change is not None:
        print(f"  BTC 1h change: {btc_1h_change:+.2f}% "
              f"(alt longs blocked if <= {BTC_DOMINANCE_GUARD_PCT}%)")

    # Alt position cap (Tier 2 only)
    alt_open = _count_alt_open_positions()
    print(f"  Open Tier 2 alt positions: {alt_open}/{MAX_ALT_POSITIONS}")

    equity = account["equity"] if account else 0

    # ── Phase 1: collect candidates ──
    candidates: list[dict] = []
    for symbol in CRYPTO_SYMBOLS:
        signal = check_crypto_signal(symbol, btc_1h_change=btc_1h_change)
        if not signal:
            continue
        # Skip Tier 2 longs if we're at alt cap
        if signal["tier"] >= 2 and signal["action"] == "BUY" and alt_open >= MAX_ALT_POSITIONS:
            print(f"  >>> {symbol} skipped — alt cap ({alt_open}/{MAX_ALT_POSITIONS})")
            continue
        if has_open_position(symbol):
            print(f"  >>> {signal['action']} {symbol} pominięty (otwarta pozycja)")
            continue
        candidates.append(signal)

    if not candidates:
        print(f"  No candidates after filters — quiet scan")
        notify_summary("Crypto Monitor", 0, 0)
        return

    # ── Phase 2: optional LLM Curator filter ──
    candidates = _maybe_curate(candidates, account, btc_1h_change)
    if not candidates:
        print(f"  Curator rejected all candidates — no entries this scan")
        notify_summary("Crypto Monitor", 0, 0)
        return

    # ── Phase 3: emit (max 3 per run — predator philosophy: quality over volume) ──
    alerts_sent = 0
    for signal in candidates[:3]:
        new_size = round(signal["size_usd"] * size_mult)
        ok, combined = concentration_ok(signal["symbol"], new_size, equity=equity)
        if not ok:
            print(f"  >>> {signal['action']} {signal['symbol']} pominięty "
                  f"(concentration {combined:.1f}% > 40%)")
            continue
        signal["size_usd"] = new_size
        print(f"  >>> SYGNAŁ: {signal['action']} {signal['symbol']}! "
              f"size=${new_size} concentration={combined:.1f}%")
        sent = send_alert(signal)
        if sent:
            alerts_sent += 1
        notify_signal(signal, sent)

    notify_summary("Crypto Monitor", alerts_sent, alerts_sent)
    print(f"  Wysłano alertów: {alerts_sent}")


def _maybe_curate(candidates: list[dict], account: dict | None,
                    btc_1h_change: float | None) -> list[dict]:
    """
    Optional Curator filter — analog to reddit-monitor. Fail-soft: if
    USE_CRYPTO_CURATOR=false / Worker URL missing / 429 / timeout →
    return candidates unchanged (heuristic order preserved).
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from llm_curator import curate, filter_signals_via_curator
    except ImportError:
        return candidates

    eq = float((account or {}).get("equity", 100_000)) or 100_000
    try:
        positions = get_open_positions()
    except Exception:
        positions = []
    pos_summary = []
    for p in positions:
        try:
            pct = (abs(p["market_value"]) / eq * 100) if eq > 0 else 0
        except Exception:
            pct = 0
        pos_summary.append({
            "symbol":      p["symbol"],
            "asset_class": p["asset_class"],
            "side":        p["side"],
            "qty":         round(p["qty"], 6),
            "pl_pct":      round(p["unrealized_plpc"] * 100, 2),
            "pct_equity":  round(pct, 1),
        })

    account_context = {
        "equity":             eq,
        "daily_pl_pct":       float((account or {}).get("daily_pl_pct", 0)),
        "open_positions":     pos_summary,
        "btc_1h_change_pct":  btc_1h_change,
        "alt_open_count":     _count_alt_open_positions(),
    }
    print(f"  Curator: validating {len(candidates)} candidates "
          f"(BTC 1h {btc_1h_change}%, {len(pos_summary)} open positions)")
    curator_out = curate(candidates, account_context)
    if not curator_out:
        print(f"  Curator unavailable — using heuristic order (fail-soft)")
        return candidates

    sel = curator_out.get("selected_signals") or []
    rej = curator_out.get("rejected_signals") or []
    print(f"  Curator: {len(sel)} selected, {len(rej)} rejected, "
          f"confidence={curator_out.get('confidence_in_curation','?')}")
    narr = curator_out.get("narrative", "")
    if narr:
        print(f"  Curator: {narr[:200]}")
    for r in rej[:5]:
        print(f"    REJECT {r.get('ticker','?')}: {r.get('reason','?')}")
    return filter_signals_via_curator(candidates, curator_out)


# ─── Start ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_scan()
