"""
Momentum Breakout Price Monitor — Aggressive Edition
Strategia: LONG (momentum) + SHORT (overbought reversal)
Wyslaje alerty do Cloudflare Worker co 5 minut podczas sesji gieldowej
"""

import os
import sys
import time
import requests
import schedule
import pytz
from datetime import datetime, timedelta

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

# v3.27 — watchlist-aware diagnostics (ETAP 8). Fail-soft.
try:
    from watchlist_diag import (  # type: ignore
        load_watchlist_cache_for_scan as _watchlist_load,
        diag_watchlist_scan_started as _watchlist_started,
        diag_watchlist_scan_finished as _watchlist_finished,
    )
except Exception:
    try:
        from shared.watchlist_diag import (  # type: ignore
            load_watchlist_cache_for_scan as _watchlist_load,
            diag_watchlist_scan_started as _watchlist_started,
            diag_watchlist_scan_finished as _watchlist_finished,
        )
    except Exception:
        def _watchlist_load(*_a, **_kw):  # type: ignore
            return {}
        def _watchlist_started(*_a, **_kw):  # type: ignore
            return False
        def _watchlist_finished(*_a, **_kw):  # type: ignore
            return None

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
    from notify import notify_signal, notify_summary
    from risk_guards import vix_guard, has_open_position, daily_drawdown_guard, get_account_status, concentration_ok
    from market_data import get_daily_bars, compute_reaction_metrics
    from alpaca_orders import execute_stock_signal
    from learning_state import load_strategy_state, is_ticker_enabled, disabled_tickers
    # v3.0 (2026-05-12) Event Switch + Momentum Score
    from regime import detect_regime, is_ticker_allowed
    from momentum_score import score_symbol
    from profile import load_profile, load_watchlists, profile_value
    from defensive_mode import is_defensive_mode_active
except ImportError:
    def notify_signal(*a, **k): pass
    def notify_summary(*a, **k): pass
    def vix_guard(): return ("OK", 1.0)
    def has_open_position(_): return False
    def daily_drawdown_guard(account=None): return ("OK", "stub")
    def get_account_status(): return None
    def concentration_ok(_s, _n, equity=None): return (True, 0.0)
    def get_daily_bars(symbol, days=35): return None
    def compute_reaction_metrics(_s): return None
    def execute_stock_signal(_s): return None
    def load_strategy_state(_): return {}
    def is_ticker_enabled(_): return True
    def disabled_tickers(): return []
    def detect_regime(_=None): return {"regime":"NEUTRAL","source":"fallback",
                                         "allowed_buckets":[],"size_multiplier":1.0,
                                         "options_side_bias":None,"max_alt_positions":3}
    def is_ticker_allowed(_t, _r): return (True, "stub")
    def score_symbol(_t, _b, **kw): return {"score":0.0,"tradeable":False,"reason":"stub"}
    def load_profile(): return {}
    def load_watchlists(): return {}
    def profile_value(_p, default=None): return default
    def is_defensive_mode_active(): return False

# Default execution path: AUTO_EXECUTE via Alpaca REST (no routine).
USE_ROUTINE = os.environ.get("USE_ROUTINE", "false").lower() == "true"

# ─── Konfiguracja ───────────────────────────────────────────────────────────

CLOUDFLARE_WORKER_URL = os.environ.get(
    "CLOUDFLARE_WORKER_URL",
    "https://tradingview-proxy.mikosbartlomiej.workers.dev"
)

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

# v3.0 (2026-05-12): tickers come from config/watchlists.json buckets.
# Static fallbacks here are used only when watchlists.json unavailable.
TICKERS_LONG  = ["AAPL", "MSFT", "GOOGL", "NVDA", "META", "AMZN", "TSLA",
                 "SPY", "QQQ",
                 "AMD", "AVGO", "SMH",                   # v3.0 ai_nasdaq_semis
                 "XLE", "USO", "XOM", "CVX", "OXY",      # v3.0 inflation_energy
                 "GLD", "TLT",                            # v3.0 hedge
                 "COIN", "MSTR", "ARM", "SMCI"]
TICKERS_SHORT = ["AAPL", "MSFT", "GOOGL", "NVDA", "META", "TSLA", "AMZN"]

# Lewarowane ETF
TICKERS_LEVERAGED = ["TQQQ", "SQQQ", "SPXL", "SPXS", "UPRO", "SPXU",
                     "SOXL", "SOXS", "FAS", "FAZ", "TNA", "TZA"]

# Rozmiary pozycji — v3.0 reads from watchlists.json::bucket.size_per_position_usd
# Hardcoded defaults below used only as fallback (when bucket lookup fails).
SIZE_LONG      = 10000
SIZE_SHORT     = 8000
SIZE_LEVERAGED = 6000

ATR_SL_MULT = 2.0
ATR_TP_MULT = 4.0

# ─── Finnhub API ─────────────────────────────────────────────────────────────

def finnhub_get(endpoint, params):
    """Wywoluje Finnhub API"""
    params["token"] = FINNHUB_API_KEY
    response = requests.get(
        f"https://finnhub.io/api/v1{endpoint}",
        params=params,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def get_candles(ticker, days=35):
    """Pobiera dane OHLCV za ostatnie N dni z Alpaca daily bars"""
    return get_daily_bars(ticker, days=days)


# ─── Wskazniki techniczne ────────────────────────────────────────────────────

def calculate_rsi(closes, period=14):
    """Oblicza RSI"""
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


def calculate_atr(highs, lows, closes, period=14):
    """Average True Range — miara zmiennosci"""
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i]  - closes[i-1]),
        )
        trs.append(tr)
    return sum(trs[-period:]) / period


# ─── Sygnaly LONG ────────────────────────────────────────────────────────────

def check_long_signal(ticker):
    """
    Momentum Breakout LONG:
    1. Cena > 20-dniowe max (breakout)
    2. Wolumen > 1.5x srednia 20d (potwierdzenie)
    3. RSI 50-70 (momentum, nie wykupiony)

    Honors per-ticker disable in learning-loop/state.json. Tickers
    disabled by backtest evidence (e.g. MSTR/SMCI as of 2026-05-08
    after high-beta basket showed 0% WR / -$4.5k over 4 trades) early-
    return None — banner-log per scan in run_scan() makes the skip
    visible without per-ticker spam.
    """
    if not is_ticker_enabled(ticker):
        return None
    try:
        candles = get_candles(ticker, days=35)
        if not candles or len(candles["close"]) < 22:
            return None

        closes  = candles["close"]
        highs   = candles["high"]
        lows    = candles["low"]
        volumes = candles["volume"]

        current_price  = closes[-1]
        current_volume = volumes[-1]

        high_20d   = max(highs[-21:-1])
        avg_volume = sum(volumes[-21:-1]) / 20
        rsi        = calculate_rsi(closes)
        atr        = calculate_atr(highs, lows, closes)

        price_breakout = current_price > high_20d
        volume_ok      = current_volume > avg_volume * 1.5
        rsi_ok         = rsi is not None and 50 <= rsi <= 70

        print(
            f"  LONG {ticker}: cena={current_price:.2f} high20d={high_20d:.2f} "
            f"vol={current_volume/avg_volume:.2f}x RSI={rsi:.1f if rsi else 'N/A'} "
            f"| breakout={price_breakout} vol={volume_ok} rsi={rsi_ok}"
        )

        if price_breakout and volume_ok and rsi_ok:
            atr_val     = atr or current_price * 0.02
            stop_loss   = round(current_price - ATR_SL_MULT * atr_val, 2)
            take_profit = round(current_price + ATR_TP_MULT * atr_val, 2)
            size        = SIZE_LEVERAGED if ticker in TICKERS_LEVERAGED else SIZE_LONG
            return {
                "symbol":      ticker,
                "action":      "BUY",
                "strategy":    "momentum-long",
                "price":       round(current_price, 2),
                "stop_loss":   stop_loss,
                "take_profit": take_profit,
                "size_usd":    size,
                "rsi":         round(rsi, 1),
                "atr":         round(atr_val, 2),
            }

    except Exception as e:
        print(f"  {ticker} LONG error: {e}")

    return None


# ─── Sygnaly SHORT ───────────────────────────────────────────────────────────

def check_short_signal(ticker):
    """
    Overbought Reversal SHORT:
    1. RSI > 72 (ekstremalnie wykupiony)
    2. Cena blisko 20-dniowego max (resistance zone)
    3. Wolumen maleje < 0.8x srednia (zanikajacy impet)
    4. Cena < wczorajszego otwarcia (bearish intraday)

    Honors learning-loop state.json: if `enabled=False` the strategy is
    paused (set by 2026-05-08 backtest evidence — 11% WR / -$2,065 over
    9 trades on 6mo mega-cap basket. Re-enable manually after refactor
    to add a market-regime filter; do not let adapter auto-resume).
    """
    state = load_strategy_state("overbought-short")
    if not state.get("enabled", True):
        # Quiet skip — log once at module level (see run_scan banner) so
        # we don't spam every cron tick with the same message.
        return None
    try:
        candles = get_candles(ticker, days=35)
        if not candles or len(candles["close"]) < 22:
            return None

        closes  = candles["close"]
        highs   = candles["high"]
        lows    = candles["low"]
        opens   = candles["open"]
        volumes = candles["volume"]

        current_price  = closes[-1]
        current_volume = volumes[-1]
        prev_open      = opens[-2]

        high_20d    = max(highs[-21:-1])
        avg_volume  = sum(volumes[-21:-1]) / 20
        rsi         = calculate_rsi(closes)
        atr         = calculate_atr(highs, lows, closes)

        rsi_overbought  = rsi is not None and rsi > 72
        near_resistance = current_price >= high_20d * 0.98   # w top 2% od 20d max
        volume_fading   = current_volume < avg_volume * 0.8
        bearish_candle  = current_price < prev_open           # close < prev open

        print(
            f"  SHORT {ticker}: cena={current_price:.2f} high20d={high_20d:.2f} "
            f"vol={current_volume/avg_volume:.2f}x RSI={rsi:.1f if rsi else 'N/A'} "
            f"| rsi_ob={rsi_overbought} resistance={near_resistance} "
            f"vol_fade={volume_fading} bearish={bearish_candle}"
        )

        # Wymagamy 3 z 4 warunkow (bardziej agresywne)
        conditions_met = sum([rsi_overbought, near_resistance, volume_fading, bearish_candle])
        if rsi_overbought and conditions_met >= 3:
            atr_val     = atr or current_price * 0.02
            stop_loss   = round(current_price + ATR_SL_MULT * atr_val, 2)   # SL powyzej ceny (short)
            take_profit = round(current_price - ATR_TP_MULT * atr_val, 2)   # TP ponizej ceny (short)
            return {
                "symbol":      ticker,
                "action":      "SELL_SHORT",
                "strategy":    "overbought-short",
                "price":       round(current_price, 2),
                "stop_loss":   stop_loss,
                "take_profit": take_profit,
                "size_usd":    SIZE_SHORT,
                "rsi":         round(rsi, 1),
                "atr":         round(atr_val, 2),
                "conditions":  conditions_met,
            }

    except Exception as e:
        print(f"  {ticker} SHORT error: {e}")

    return None


# ─── Sygnaly lewarowanych ETF ─────────────────────────────────────────────────

def check_leveraged_signals():
    """
    Lewarowane ETF — trend following:
    TQQQ (3x QQQ long):  gdy QQQ w silnym uptrend (RSI 55-68)
    SQQQ (3x QQQ short): gdy QQQ w silnym downtrend (RSI < 35)
    SPXL (3x SPY long):  gdy SPY breakout
    SPXS (3x SPY short): gdy SPY sell-off
    """
    signals = []
    for ticker in TICKERS_LEVERAGED:
        sig = check_long_signal(ticker)
        if sig:
            signals.append(sig)
    return signals


# ─── Wysylanie alertu ────────────────────────────────────────────────────────

def send_alert(alert):
    """
    Default: AUTO_EXECUTE via Alpaca REST (places bracket order directly).
    USE_ROUTINE=true -> legacy Cloudflare Worker -> routine path.
    """
    if not USE_ROUTINE:
        order = execute_stock_signal(alert)
        if order:
            print(f"  Order {alert['action']} {alert['symbol']}: id={order.get('id')} qty={order.get('qty')} @ ${order.get('limit_price')}")
            return True
        print(f"  Order {alert['action']} {alert['symbol']}: REJECTED (Alpaca)")
        return False

    # Legacy routine path (opt-in)
    try:
        response = requests.post(
            CLOUDFLARE_WORKER_URL,
            json=alert,
            timeout=30,
        )
        print(f"  Routine forward {alert['action']} {alert['symbol']}: HTTP {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        print(f"  BLAD wysylania alertu: {e}")
        return False


# ─── Glowna petla ────────────────────────────────────────────────────────────

def is_market_open():
    et = pytz.timezone("America/New_York")
    now = datetime.now(et)
    if now.weekday() >= 5:
        return False
    market_open  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return market_open <= now <= market_close


def _build_market_signals_for_regime() -> dict:
    """
    Build market_signals dict for regime.detect_regime().
    VIX + SPY 5d + XLE 5d (energy proxy) + (BTC 24h optional via crypto-monitor).
    All optional — missing fields default to None, regime falls back to NEUTRAL.
    """
    sig = {}
    # VIX — already cached in shared.risk_guards
    try:
        from risk_guards import get_vix
    except ImportError:
        from shared.risk_guards import get_vix
    sig["vix"] = get_vix()
    # SPY 5d return — via daily bars
    spy = get_daily_bars("SPY", days=10)
    if spy and spy.get("close") and len(spy["close"]) >= 6:
        prev = spy["close"][-6]
        curr = spy["close"][-1]
        if prev > 0:
            sig["spy_5d_pct"] = (curr / prev - 1) * 100
    # Energy 5d — XLE proxy
    xle = get_daily_bars("XLE", days=10)
    if xle and xle.get("close") and len(xle["close"]) >= 6:
        prev = xle["close"][-6]
        curr = xle["close"][-1]
        if prev > 0:
            sig["energy_5d_pct"] = (curr / prev - 1) * 100
    return sig


def run_checks():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not is_market_open():
        print(f"[{now_str}] Gielda zamknieta — pomijam sprawdzenie")
        return

    print(f"\n[{now_str}] === PRICE MONITOR (v3.0 Aggressive Momentum + Event Switch) ===")
    _diag("price-monitor", DIAG_RAN, {"now": now_str})

    # v3.0 defensive mode check — if armed, only existing exits work; no new entries
    if is_defensive_mode_active():
        print(f"  [DEFENSIVE MODE ACTIVE] new entries blocked. Existing exits keep working.")
        notify_summary("Price Monitor", 0, 0)
        return

    # v2.0 safety net: account-level circuit breaker BEFORE VIX guard
    account = get_account_status()
    dd_status, _ = daily_drawdown_guard(account=account)
    if dd_status == "HALT":
        notify_summary("Price Monitor", 0, 0)
        return

    vix_status, vix_size_mult = vix_guard()
    if vix_status == "HALT":
        notify_summary("Price Monitor", 0, 0)
        return

    # v3.0 Event Switch — detect current market regime
    market_signals = _build_market_signals_for_regime()
    regime_info = detect_regime(market_signals)
    print(f"  REGIME: {regime_info['regime']} ({regime_info['source']}) — {regime_info['reason']}")
    print(f"    allowed_buckets: {regime_info['allowed_buckets']}")
    print(f"    size_multiplier: {regime_info['size_multiplier']:.2f}")

    # v3.0 combined size multiplier: VIX × regime
    size_mult = vix_size_mult * regime_info['size_multiplier']

    equity = account["equity"] if account else 0
    signals_found = 0
    alerts_sent   = 0

    # v3.14.0 (2026-06-02) — confidence_inputs helper (closes CONF-002).
    try:
        from confidence_builder import build_confidence_inputs as _build_ci
    except ImportError:
        try:
            from shared.confidence_builder import build_confidence_inputs as _build_ci  # type: ignore
        except ImportError:
            def _build_ci(**_kw):  # type: ignore
                return None

    # v3.17.0 (2026-06-04) — feedback modules helper (Task 5).
    # Wires instrument_profile + liquidity_sweep + lead_lag analyses
    # into confidence_inputs. Fail-soft: missing helpers / data → ctx={}.
    try:
        from feedback_modules_helper import build_feedback_confidence_context as _build_feedback_ctx
    except ImportError:
        try:
            from shared.feedback_modules_helper import build_feedback_confidence_context as _build_feedback_ctx  # type: ignore
        except ImportError:
            def _build_feedback_ctx(**_kw):  # type: ignore
                return {}

    def _attach_ci(signal_dict, *, side, score=None, regime=None,
                    bars=None, index_closes=None):
        try:
            sym = signal_dict.get("symbol") or signal_dict.get("ticker") or ""
            # v3.17.0 — feedback context (instrument profile + sweep + lead-lag)
            try:
                fb_ctx = _build_feedback_ctx(
                    symbol=sym,
                    bars=bars,
                    index_closes=index_closes,
                )
            except Exception:
                fb_ctx = {}
            signal_dict["confidence_inputs"] = _build_ci(
                strategy      = signal_dict.get("strategy", "momentum-long"),
                primary_score = score,
                regime        = regime or regime_info["regime"],
                bars          = bars,
                bars_count    = 60,                # 60-day backtest window
                account_status= account,
                **fb_ctx,
            )
        except Exception as _ci_e:
            print(f"    confidence_inputs build failed (non-fatal): {type(_ci_e).__name__}")

    # v3.0 score-based pre-ranking — rank LONG candidates by composite score,
    # keep only top_n (focus on leaders). Score reads from config/aggressive_profile.json.
    top_n = int(profile_value("scoring.top_n_picks", 7))
    min_score = float(profile_value("scoring.min_score_for_entry", 0.35))

    # Filter: enabled + regime-allowed bucket
    candidates_long = []
    for t in TICKERS_LONG:
        if not is_ticker_enabled(t):
            continue
        # v3.0 regime gate: skip tickers not in allowed_buckets
        allowed, why = is_ticker_allowed(t, regime_info)
        if not allowed:
            continue
        candidates_long.append(t)

    paused_long = [t for t in TICKERS_LONG if not is_ticker_enabled(t)]
    regime_blocked = [t for t in TICKERS_LONG
                       if is_ticker_enabled(t) and t not in candidates_long]
    if paused_long:
        print(f"  [LONG] Paused via learning-loop state: {', '.join(paused_long)}")
    if regime_blocked:
        print(f"  [LONG] Regime-blocked ({regime_info['regime']}): {', '.join(regime_blocked)}")

    # Score every candidate; rank by score; pick top_n
    spy_bars = get_daily_bars("SPY", days=35)
    qqq_bars = get_daily_bars("QQQ", days=35)
    # v3.17.0 — pre-extract SPY closes for lead-lag (fail-soft).
    spy_closes = None
    try:
        if spy_bars and spy_bars.get("close"):
            spy_closes = [float(x) for x in spy_bars["close"]]
    except Exception:
        spy_closes = None
    # v3.17.0 — cache per-ticker bars so _attach_ci can reuse without
    # re-fetching (avoids extra Alpaca calls / rate-limit risk).
    bars_by_ticker: dict[str, dict] = {}
    scored = []
    for t in candidates_long:
        bars = get_daily_bars(t, days=35)
        if not bars:
            continue
        bars_by_ticker[t] = bars
        s = score_symbol(t, bars, spy_bars=spy_bars, qqq_bars=qqq_bars)
        scored.append(s)
    scored.sort(key=lambda x: x["score"], reverse=True)
    top_picks = scored[:top_n]
    if top_picks:
        print(f"  [LONG] Top {len(top_picks)} by score:")
        for s in top_picks:
            print(f"    {s['ticker']:6s} score={s['score']:+.3f}  {s['reason']}")

    # Process top picks: only those above min_score get full check
    print(f"  [LONG] Processing top picks with score >= {min_score:.2f}...")
    # v3.27 ETAP 8 — load watchlist cache once per run.
    _watchlist_cache = _watchlist_load()
    for s in top_picks:
        if s["score"] < min_score:
            continue
        ticker = s["ticker"]
        # v3.27 — watchlist-aware diag: notify scan started (no-op when
        # symbol is not on the watchlist).
        _watchlist_started("price-monitor", ticker, _watchlist_cache)
        signal = check_long_signal(ticker)
        if not signal:
            _watchlist_finished(
                "price-monitor", ticker, _watchlist_cache,
                signal_detected=False,
                distance=(1.0 - max(0.0, min(1.0, s["score"]))),
            )
        if signal:
            if has_open_position(ticker):
                print(f"    >>> SYGNAL LONG {ticker} pominiety (otwarta pozycja)")
                continue
            new_size = round(signal["size_usd"] * size_mult)
            ok, combined = concentration_ok(ticker, new_size, equity=equity)
            if not ok:
                print(f"    >>> SYGNAL LONG {ticker} pominiety (concentration {combined:.1f}% > 40%)")
                continue
            signal["size_usd"] = new_size
            signal["regime"] = regime_info["regime"]
            signal["momentum_score"] = s["score"]
            signal["score_reason"] = s["reason"]
            _attach_ci(signal, side="buy", score=s["score"],
                        bars=bars_by_ticker.get(ticker),
                        index_closes=spy_closes)
            print(f"    >>> SYGNAL LONG: {ticker}! score={s['score']:+.3f} regime={regime_info['regime']} size=${new_size}")
            signals_found += 1
            _diag("price-monitor", DIAG_SIGNAL_DETECTED,
                  {"symbol": ticker, "side": "long", "score": s.get("score")})
            # v3.27 — watchlist-aware diag: trigger crossed (no-op when
            # symbol is not on the watchlist).
            _watchlist_finished(
                "price-monitor", ticker, _watchlist_cache,
                signal_detected=True,
                signal_id=signal.get("client_order_id"),
                strategy_id_override=signal.get("strategy", "momentum-long"),
            )
            _diag("price-monitor", DIAG_EMIT_ATTEMPTED,
                  {"symbol": ticker, "strategy": "momentum-long"})
            # v3.22.0 — observability emit BEFORE alert dispatch so the
            # ledger captures the signal even if the alert send fails.
            # NEVER places a trade.
            try:
                emit_monitor_signal(
                    source_monitor="price-monitor",
                    strategy_id=signal.get("strategy", "momentum-long"),
                    symbol=ticker,
                    asset_class="us_equity",
                    side="long",
                    action="BUY",
                    entry_capable=True,
                    raw_signal={
                        "score":     s["score"],
                        "rsi":       signal.get("rsi"),
                        "atr":       signal.get("atr"),
                        "price":     signal.get("price"),
                        "stop_loss": signal.get("stop_loss"),
                        "take_profit": signal.get("take_profit"),
                    },
                    confidence_inputs=signal.get("confidence_inputs")
                        or {"primary_score": float(s["score"])},
                    risk_inputs={"size_usd": new_size},
                    market_regime={"regime": regime_info["regime"]},
                    metadata={"audit_link": f"price-long-{ticker}"},
                )
            except Exception:
                pass
            sent = send_alert(signal)
            if sent:
                alerts_sent += 1
                _diag("price-monitor", DIAG_EMIT_SUCCESS, {"symbol": ticker})
            else:
                _diag("price-monitor", DIAG_EMIT_FAILED, {"symbol": ticker})
            notify_signal(signal, sent)
        time.sleep(0.3)

    # SHORT signals — honors learning-loop state.json overbought-short.enabled
    short_state = load_strategy_state("overbought-short")
    short_enabled = short_state.get("enabled", True)
    if not short_enabled:
        print(f"\n[SHORT] overbought-short paused via learning-loop state — "
              f"skipping ({short_state.get('rationale', 'no reason logged')})")
    else:
        print(f"\n[SHORT] Sprawdzam {', '.join(TICKERS_SHORT)}")
    for ticker in (TICKERS_SHORT if short_enabled else []):
        signal = check_short_signal(ticker)
        if signal:
            if has_open_position(ticker):
                print(f"  >>> SYGNAL SHORT {ticker} pominiety (otwarta pozycja)")
                continue
            new_size = round(signal["size_usd"] * size_mult)
            ok, combined = concentration_ok(ticker, new_size, equity=equity)
            if not ok:
                print(f"  >>> SYGNAL SHORT {ticker} pominiety (concentration {combined:.1f}% > 40%)")
                continue
            signal["size_usd"] = new_size
            # v3.17.0 — fetch bars fail-soft for SHORT side feedback context
            short_bars = None
            try:
                short_bars = get_daily_bars(ticker, days=35)
            except Exception:
                short_bars = None
            _attach_ci(signal, side="sell_short",
                        bars=short_bars,
                        index_closes=spy_closes)
            print(f"  >>> SYGNAL SHORT: {ticker}! (concentration={combined:.1f}%)")
            signals_found += 1
            sent = send_alert(signal)
            if sent:
                alerts_sent += 1
            notify_signal(signal, sent)
        time.sleep(0.5)

    # Lewarowane ETF
    print(f"\n[LEVERAGED] Sprawdzam {', '.join(TICKERS_LEVERAGED)}")
    for ticker in TICKERS_LEVERAGED:
        signal = check_long_signal(ticker)
        if signal:
            if has_open_position(ticker):
                print(f"  >>> SYGNAL LEVERAGED {ticker} pominiety (otwarta pozycja)")
                continue
            signal["strategy"] = "leveraged-etf"
            new_size = round(SIZE_LEVERAGED * size_mult)
            ok, combined = concentration_ok(ticker, new_size, equity=equity)
            if not ok:
                print(f"  >>> SYGNAL LEVERAGED {ticker} pominiety (concentration {combined:.1f}% > 40%)")
                continue
            signal["size_usd"] = new_size
            # v3.17.0 — fetch bars fail-soft for leveraged feedback context
            lev_bars = None
            try:
                lev_bars = get_daily_bars(ticker, days=35)
            except Exception:
                lev_bars = None
            _attach_ci(signal, side="buy",
                        bars=lev_bars,
                        index_closes=spy_closes)
            print(f"  >>> SYGNAL LEVERAGED: {ticker}! (concentration={combined:.1f}%)")
            signals_found += 1
            sent = send_alert(signal)
            if sent:
                alerts_sent += 1
            notify_signal(signal, sent)
        time.sleep(0.5)

    if signals_found == 0:
        _diag("price-monitor", DIAG_NO_SIGNAL,
              {"alerts_sent": alerts_sent})
    notify_summary("Price Monitor", signals_found, alerts_sent)
    print(f"\n[{now_str}] Sygnaly: {signals_found}, alerty wyslane: {alerts_sent}. Nastepne sprawdzenie za 5 minut.\n")


# ─── Start ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    once_mode = "--once" in sys.argv

    print("=" * 60)
    print("  Momentum Monitor — Aggressive Edition (LONG + SHORT)")
    print(f"  Tryb: {'jednorazowy (GitHub Actions)' if once_mode else 'ciagly (lokalny)'}")
    print(f"  LONG:     {', '.join(TICKERS_LONG)}")
    print(f"  SHORT:    {', '.join(TICKERS_SHORT)}")
    print(f"  LEVERAGED:{', '.join(TICKERS_LEVERAGED)}")
    print(f"  Worker URL: {CLOUDFLARE_WORKER_URL}")
    print("=" * 60 + "\n")

    # v3.10 (2026-05-27) — Finnhub is OPTIONAL (used only for news fetch
    # in geo-monitor; price-monitor uses Alpaca IEX bars). Warn but proceed.
    if not FINNHUB_API_KEY:
        print("WARN: FINNHUB_API_KEY not set (price-monitor doesn't require it; only used for fallback news fetch)")

    def _heartbeat_ping():
        # v3.14.0 (2026-06-02) — heartbeat ping (closes ARCH-001/RUNTIME-002/CONF-003).
        try:
            import sys as _sys, os as _os
            _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "shared"))
            from heartbeat import ping as _hb_ping
            _hb_ping("price-monitor", status="ok")
        except Exception as _hb_e:
            print(f"  heartbeat ping failed (non-fatal): {type(_hb_e).__name__}")

    if once_mode:
        run_checks()
        _heartbeat_ping()
    else:
        run_checks()
        _heartbeat_ping()
        schedule.every(5).minutes.do(run_checks)
        schedule.every(5).minutes.do(_heartbeat_ping)
        while True:
            schedule.run_pending()
            time.sleep(30)
