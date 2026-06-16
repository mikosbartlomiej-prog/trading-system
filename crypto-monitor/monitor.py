from __future__ import annotations  # v3.11.3 part 2: PEP 604 on Py 3.9.

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

# v3.24 — monitor runtime diagnostics (ETAP 9). Fail-soft: any import
# failure or write error must NEVER break the monitor.
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
        DIAG_RAN = "RAN"
        DIAG_INPUT_EMPTY = "INPUT_EMPTY"
        DIAG_NO_SIGNAL = "NO_SIGNAL"
        DIAG_SIGNAL_DETECTED = "SIGNAL_DETECTED"
        DIAG_EMIT_ATTEMPTED = "EMIT_ATTEMPTED"
        DIAG_EMIT_SUCCESS = "EMIT_SUCCESS"
        DIAG_EMIT_FAILED = "EMIT_FAILED"

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


# v3.22.0 (2026-06-07) — Signal Opportunity Ledger emit (ETAP 4).
#
# Crypto-momentum has been SILENT for 62+ days. Diagnosis: signals are
# evaluated but never recorded to the opportunity ledger, so we have no
# durable evidence of WHY trades did not fire. This helper is the single
# write-point. It is observability-only — it NEVER places trades and
# NEVER mutates the signal-decision logic.
def _emit_opportunity(*, strategy: str, symbol: str,
                      signal_state: str,
                      raw_signal: dict | None = None,
                      rsi: float | None = None,
                      confidence_inputs: dict | None = None,
                      market_regime: str | None = "NEUTRAL",
                      universe_status: str | None = "WHITELISTED",
                      gate_decisions: list | None = None,
                      rejection_reasons: list | None = None,
                      paper_action: str | None = None,
                      audit_link: str | None = None) -> None:
    """Append one entry to the daily opportunity ledger.

    Fail-soft: any exception (import failure, disk error, etc.) must NOT
    crash the monitor or change trade behavior. Decision points pass
    a paper_action of "signal_detected" / "executed" / "rejected" so the
    ledger captures both fires and misses.
    """
    # v3.22 migration: route through shared.signal_emitter.emit_signal_opportunity
    # instead of calling record_opportunity directly. This gives us:
    # - canonical SignalEvent shape
    # - idempotency cache
    # - automatic confidence computation when confidence_inputs are present
    # - one validated write-path so the learning loop only ever sees rows that
    #   passed v3.22's validator
    try:
        try:
            from signal_emitter import emit_signal_opportunity  # type: ignore
            from signal_event import SignalEvent, build_signal_id  # type: ignore
        except ImportError:
            from shared.signal_emitter import emit_signal_opportunity  # type: ignore
            from shared.signal_event import SignalEvent, build_signal_id  # type: ignore
    except Exception:
        return
    try:
        ts_iso = datetime.now(timezone.utc).isoformat()
        sid = build_signal_id(strategy, symbol, ts_iso, "crypto-monitor")
        payload = dict(raw_signal or {})
        if rsi is not None and "rsi" not in payload:
            payload["rsi"] = rsi
        payload.setdefault("signal_state", signal_state)

        # Map signal_state → SignalEvent.action.
        state_upper = (signal_state or "").upper()
        if state_upper.startswith("HALTED") or state_upper.startswith("BLOCKED"):
            action = "HALTED"
            entry_capable = False
            side = "n/a"
        elif state_upper in ("DETECTED",):
            action = payload.get("action", "BUY") or "BUY"
            entry_capable = True
            side = "long" if str(action).upper().startswith("BUY") else "short"
        elif state_upper in ("EXECUTED", "BUY"):
            action = "BUY"
            entry_capable = True
            side = "long"
        elif state_upper in ("REJECTED", "REJECT"):
            action = "REJECT"
            entry_capable = False
            side = "n/a"
        else:
            action = "DETECTED"
            entry_capable = False
            side = "n/a"

        event = SignalEvent(
            signal_id=sid,
            strategy_id=strategy,
            symbol=symbol,
            asset_class="crypto",
            side=side,
            action=action,
            timestamp_iso=ts_iso,
            source_monitor="crypto-monitor",
            pipeline="monitor",
            evidence_source="PAPER",
            entry_capable=entry_capable,
            raw_signal=payload,
            confidence_inputs=(confidence_inputs or {}) if entry_capable else {},
            risk_inputs={"strategy": strategy, "symbol": symbol} if entry_capable else {},
            market_regime={"regime": market_regime} if market_regime else {},
            universe_status={"status": universe_status} if universe_status else {},
            metadata={"audit_link": audit_link} if audit_link else {},
        )
        emit_signal_opportunity(event)
    except Exception as _e:
        # Observability layer never breaks the monitor.
        print(f"  opportunity-ledger emit failed (non-fatal): "
              f"{type(_e).__name__}")

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

# v3.11.3 (2026-05-30) — OVERSOLD-BOUNCE path (alternative to predator filter).
# Why: predator-bracket [3%, 15%] blocked all entries for 45+ days while LLM
# Senior PM screamed "BTC RSI 22 oversold!" daily. Symptom: zero placements
# from 2026-04-15 → 2026-05-29. Root cause: deep-oversold setups have flat
# or negative 24h-move (after crash already happened), NOT predator's
# preferred 3-15% momentum bracket.
# Fix: when RSI ≤ OVERSOLD_BOUNCE_RSI_MAX AND 24h-move not catastrophic,
# BYPASS the predator bracket AND relax breakout to 1-bar reversal.
# Tag separately as "crypto-oversold-bounce" so analyzer attributes correctly.
OVERSOLD_BOUNCE_RSI_MAX        = 30.0   # only fire when RSI ≤ 30 (deep oversold)
OVERSOLD_BOUNCE_MIN_MOVE_PCT   = -10.0  # but don't catch knife: 24h-move must be ≥ -10%
# v3.13.3 (2026-06-02) — relaxed for QUIET oversold markets.
# LIVE ROOT CAUSE (06-01 → 06-02): BTC RSI 24.9 for 3+ days but
# oversold-bounce never fired because:
#   * 24h-move ~-0.17% (flat consolidation post-crash)
#   * volume below average (no panic, just exhaustion)
#   * hourly closes oscillating ±0.05% → strict closes[-1]>closes[-2] reversal fails
# Each individual bar may not "reverse" but the 3-bar trend can stabilize.
# Lowering the bar to: not-falling over last 3 bars + volume ≥ 0.25×.
OVERSOLD_BOUNCE_VOL_MULT_FLOOR = 0.25   # was 0.5 — quiet oversold often has below-average volume
OVERSOLD_BOUNCE_REVERSAL_BARS  = 3      # was 2 (strict 1-bar) — accept stability over last 3 bars
# Stability rule: avg(closes[-3:]) >= closes[-4] (last 3-bar avg above
# the bar from 3 hours ago = not falling). Catches stabilization without
# requiring hourly bullish candle.
MAX_ALT_POSITIONS = 3         # cap simultaneous Tier 2 open positions

# Global circuit breakers
CRYPTO_MAX_EXPOSURE_USD = 25000   # v2.0 — combined cap

# Shared RSI thresholds
RSI_LONG_MIN  = 45
RSI_SHORT_MAX = 35

# v3.8.1 (2026-05-15): Alpaca paper crypto = LONG-only.
# Every SELL_SHORT order returns 403 "insufficient balance" because there is
# no margin shorting on crypto. The crypto-breakdown strategy was generating
# spam emails ("Alert NOT sent (error)") all session. Until Alpaca adds
# crypto margin shorting (or we route via inverse instruments) the SHORT
# emission must be silenced at source. Default False; flip via env if
# Alpaca ever changes.
ENABLE_CRYPTO_SHORT = os.environ.get("ENABLE_CRYPTO_SHORT", "false").lower() == "true"

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

    # ── OVERSOLD-BOUNCE entry (v3.11.3 — pre-predator, must check FIRST) ──
    # Fires when RSI is deep-oversold AND 24h-move is not catastrophic AND
    # current bar prints higher close than prior bar (1-bar reversal).
    # Bypasses predator bracket + 20-bar breakout (those filters miss
    # post-crash bounce setups by design).
    # v3.13.3 (2026-06-02) — stabilization rule: average of last 3 hourly
    # closes >= the close from 3 hours ago. Catches "not falling" without
    # requiring a strict per-bar bullish reversal.
    stable_or_rising = False
    if len(closes) >= 4:
        recent_avg = sum(closes[-3:]) / 3.0
        baseline   = closes[-4]
        stable_or_rising = recent_avg >= baseline

    if (
        rsi is not None
        and rsi <= OVERSOLD_BOUNCE_RSI_MAX
        and move_24h is not None
        and move_24h >= OVERSOLD_BOUNCE_MIN_MOVE_PCT
        and len(closes) >= OVERSOLD_BOUNCE_REVERSAL_BARS + 1
        and stable_or_rising                       # 3-bar stabilization (relaxed from strict 1-bar)
        and current_volume > avg_vol * (vol_mult * OVERSOLD_BOUNCE_VOL_MULT_FLOOR)
    ):
        # Tier 2 alt-long: same BTC dominance guard as predator-long.
        if tier == 2 and btc_1h_change is not None \
                and btc_1h_change <= BTC_DOMINANCE_GUARD_PCT:
            print(f"  {symbol}: BTC 1h={btc_1h_change:+.2f}% — oversold-bounce alt long BLOCKED")
            _emit_opportunity(
                strategy="crypto-oversold-bounce", symbol=symbol,
                signal_state="REJECT", rsi=rsi, raw_signal=common,
                gate_decisions=[{"gate": "regime", "decision": "BLOCK",
                                 "reason": f"btc_1h={btc_1h_change:+.2f}% <= "
                                           f"dominance_guard={BTC_DOMINANCE_GUARD_PCT}%"}],
                rejection_reasons=["btc_dominance_guard"],
                paper_action="rejected",
            )
            # Fall through to brak sygnału (don't enter)
        else:
            # Wider stop on oversold-bounce (further from entry) — bounce
            # setups need room to breathe. SL 1.5× tier's normal sl_pct.
            stop_loss   = round(current_price * (1 - sl_pct * 1.5), 4)
            take_profit = round(current_price * (1 + tp_pct), 4)
            print(f"  OVERSOLD-BOUNCE {symbol} [T{tier}]: ${current_price:.2f} "
                  f"RSI={rsi:.1f} ≤ {OVERSOLD_BOUNCE_RSI_MAX} "
                  f"24h={move_24h:+.2f}% reversal (prior={closes[-2]:.2f} → {current_price:.2f}) "
                  f"vol={common['volume_ratio']}x")
            sig = {**common,
                "action":      "BUY",
                "strategy":    "crypto-oversold-bounce",
                "stop_loss":   stop_loss,
                "take_profit": take_profit,
                "size_usd":    cfg["size_long"],
            }
            _emit_opportunity(
                strategy="crypto-oversold-bounce", symbol=symbol,
                signal_state="DETECTED", rsi=rsi, raw_signal=sig,
                gate_decisions=[{"gate": "quality", "decision": "PASS",
                                 "reason": "oversold_bounce_setup"}],
                paper_action="signal_detected",
            )
            return sig

    # ── PREDATOR FILTERS (apply BEFORE breakout check to short-circuit) ──
    if move_24h is not None and not (
        MOMENTUM_24H_MIN_PCT <= abs(move_24h) <= MOMENTUM_24H_MAX_PCT
    ):
        print(f"  {symbol}: move_24h={move_24h:+.2f}% poza zakresem "
              f"[{MOMENTUM_24H_MIN_PCT}%..{MOMENTUM_24H_MAX_PCT}%] — skip")
        _emit_opportunity(
            strategy="crypto-momentum", symbol=symbol,
            signal_state="REJECT", rsi=rsi, raw_signal=common,
            gate_decisions=[{"gate": "quality", "decision": "BLOCK",
                             "reason": f"predator_bracket move_24h={move_24h:+.2f}% "
                                       f"outside [{MOMENTUM_24H_MIN_PCT},"
                                       f"{MOMENTUM_24H_MAX_PCT}]"}],
            rejection_reasons=["predator_bracket"],
            paper_action="rejected",
        )
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
            _emit_opportunity(
                strategy="crypto-momentum", symbol=symbol,
                signal_state="REJECT", rsi=rsi, raw_signal=common,
                gate_decisions=[{"gate": "regime", "decision": "BLOCK",
                                 "reason": f"btc_dominance_guard "
                                           f"btc_1h={btc_1h_change:+.2f}%"}],
                rejection_reasons=["btc_dominance_guard"],
                paper_action="rejected",
            )
            return None
        stop_loss   = round(current_price * (1 - sl_pct), 4)
        take_profit = round(current_price * (1 + tp_pct), 4)
        print(f"  LONG {symbol} [T{tier}]: ${current_price:.2f} > high20=${high_20:.2f}, "
              f"RSI={rsi:.1f}, vol={common['volume_ratio']}x, 24h={common['move_24h_pct']}%")
        sig = {**common,
            "action":      "BUY",
            "strategy":    "crypto-momentum",
            "stop_loss":   stop_loss,
            "take_profit": take_profit,
            "size_usd":    cfg["size_long"],
        }
        _emit_opportunity(
            strategy="crypto-momentum", symbol=symbol,
            signal_state="DETECTED", rsi=rsi, raw_signal=sig,
            gate_decisions=[{"gate": "quality", "decision": "PASS",
                             "reason": "breakout_long"}],
            paper_action="signal_detected",
        )
        return sig

    # ── SHORT entry ────────────────────────────────────────────────────
    # Gated by ENABLE_CRYPTO_SHORT (default False as of v3.8.1) — Alpaca
    # paper crypto is LONG-only; emitting SHORT signals produces 403
    # "insufficient balance" rejects and "Alert NOT sent (error)" emails.
    # The detection block stays for observability (log only) so we can
    # flip the flag on later if margin shorting becomes available.
    if (current_price < low_20
            and current_volume > avg_vol * max(1.5, vol_mult - 0.5)
            and rsi is not None and rsi < RSI_SHORT_MAX):
        if not ENABLE_CRYPTO_SHORT:
            print(f"  SHORT {symbol} [T{tier}] detected but NOT emitted — "
                  f"crypto-breakdown disabled (Alpaca paper crypto = LONG-only). "
                  f"price=${current_price:.2f} low20=${low_20:.2f} RSI={rsi:.1f}")
            _emit_opportunity(
                strategy="crypto-breakdown", symbol=symbol,
                signal_state="REJECT", rsi=rsi, raw_signal=common,
                gate_decisions=[{"gate": "universe", "decision": "BLOCK",
                                 "reason": "alpaca_paper_crypto_long_only"}],
                rejection_reasons=["short_disabled"],
                paper_action="rejected",
            )
            return None
        stop_loss   = round(current_price * (1 + sl_pct), 4)
        take_profit = round(current_price * (1 - tp_pct), 4)
        print(f"  SHORT {symbol} [T{tier}]: ${current_price:.2f} < low20=${low_20:.2f}, "
              f"RSI={rsi:.1f}, vol={common['volume_ratio']}x, 24h={common['move_24h_pct']}%")
        sig = {**common,
            "action":      "SELL_SHORT",
            "strategy":    "crypto-breakdown",
            "stop_loss":   stop_loss,
            "take_profit": take_profit,
            "size_usd":    cfg["size_short"],
        }
        _emit_opportunity(
            strategy="crypto-breakdown", symbol=symbol,
            signal_state="DETECTED", rsi=rsi, raw_signal=sig,
            gate_decisions=[{"gate": "quality", "decision": "PASS",
                             "reason": "breakdown_short"}],
            paper_action="signal_detected",
        )
        return sig

    print(
        f"  {symbol} [T{tier}]: ${current_price:.2f} hi20=${high_20:.2f} lo20=${low_20:.2f} "
        f"RSI={f'{rsi:.1f}' if rsi else 'N/A'} vol={common['volume_ratio']}x "
        f"24h={common['move_24h_pct']}% — brak sygnału"
    )
    _emit_opportunity(
        strategy="crypto-momentum", symbol=symbol,
        signal_state="NO_SIGNAL", rsi=rsi, raw_signal=common,
        gate_decisions=[{"gate": "quality", "decision": "BLOCK",
                         "reason": "no_setup_breakout_or_bounce"}],
        rejection_reasons=["no_setup"],
        paper_action="rejected",
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

    Returns True only when an actual Alpaca order id is returned. A
    "deferred" envelope (per-instrument window block, crypto SHORT refusal,
    etc.) returns False — the signal is logged but no order placed.
    """
    if not USE_ROUTINE:
        order = execute_crypto_signal(alert)
        if order and not order.get("deferred") and order.get("id"):
            print(f"  Order {alert['action']} {alert['symbol']}: id={order.get('id')} qty={order.get('qty')} @ ${order.get('limit_price')}")
            return True
        if order and order.get("deferred"):
            print(f"  Order {alert['action']} {alert['symbol']}: DEFERRED ({order.get('reason')})")
            return False
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
    # v3.24 — runtime diagnostic: scan started.
    _diag("crypto-monitor", DIAG_RAN, {"universe_size": len(CRYPTO_SYMBOLS)})

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("BŁĄD: Brak ALPACA_API_KEY lub ALPACA_SECRET_KEY")
        sys.exit(1)

    # v2.0 safety net: account-level circuit breaker BEFORE VIX guard
    account = get_account_status()
    dd_status, dd_reason = daily_drawdown_guard(account=account)
    if dd_status == "HALT":
        # v3.22.1 — observability emit so the operator can see WHY no
        # signals were evaluated. The halt itself is correct + unchanged;
        # this is a fail-soft diagnostic record only.
        for _sym in ("BTC/USD", "ETH/USD"):
            _emit_opportunity(
                strategy="crypto-momentum",
                symbol=_sym,
                signal_state="HALTED_BY_DRAWDOWN_GUARD",
                rejection_reasons=[f"daily_drawdown_guard:{dd_reason}"],
                paper_action="halted",
                market_regime="RISK_OFF",
            )
        notify_summary("Crypto Monitor", 0, 0)
        return

    vix_status, size_mult = vix_guard()
    if vix_status == "HALT":
        for _sym in ("BTC/USD", "ETH/USD"):
            _emit_opportunity(
                strategy="crypto-momentum",
                symbol=_sym,
                signal_state="HALTED_BY_VIX_GUARD",
                rejection_reasons=["vix_guard:HALT"],
                paper_action="halted",
                market_regime="RISK_OFF",
            )
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
    # v3.8.6 (2026-05-16): verbose per-coin scan summary (LLM proposal
    # 2026-05-13 "Crypto pipeline 14+ days 0 trades — log verbose
    # rejection reasons"). After 21 days of zero crypto trades we need
    # operator visibility into whether silence is correct or pipeline
    # broken. check_crypto_signal already logs per-coin RSI / move_24h /
    # vol / RSI when no signal. Here we add aggregate summary.
    candidates: list[dict] = []
    scanned = 0
    rejected_no_signal = 0
    rejected_alt_cap = 0
    rejected_open_pos = 0
    # v3.27 ETAP 8 — load watchlist cache once for this scan.
    _watchlist_cache = _watchlist_load()
    for symbol in CRYPTO_SYMBOLS:
        scanned += 1
        # v3.27 — watchlist-aware diag: notify scan started (no-op if
        # the symbol is not on the watchlist).
        _watchlist_started("crypto-monitor", symbol, _watchlist_cache)
        signal = check_crypto_signal(symbol, btc_1h_change=btc_1h_change)
        if not signal:
            rejected_no_signal += 1
            _watchlist_finished(
                "crypto-monitor", symbol, _watchlist_cache,
                signal_detected=False,
            )
            continue
        _watchlist_finished(
            "crypto-monitor", symbol, _watchlist_cache,
            signal_detected=True,
            signal_id=(signal.get("client_order_id") or signal.get("strategy")),
            strategy_id_override=signal.get("strategy"),
        )
        # Skip Tier 2 longs if we're at alt cap
        if signal["tier"] >= 2 and signal["action"] == "BUY" and alt_open >= MAX_ALT_POSITIONS:
            print(f"  >>> {symbol} skipped — alt cap ({alt_open}/{MAX_ALT_POSITIONS})")
            rejected_alt_cap += 1
            _emit_opportunity(
                strategy=signal.get("strategy", "crypto-momentum"),
                symbol=symbol, signal_state="REJECT",
                rsi=signal.get("rsi"), raw_signal=signal,
                gate_decisions=[{"gate": "risk", "decision": "BLOCK",
                                 "reason": f"alt_cap {alt_open}/"
                                           f"{MAX_ALT_POSITIONS}"}],
                rejection_reasons=["alt_cap"],
                paper_action="rejected",
            )
            continue
        if has_open_position(symbol):
            print(f"  >>> {signal['action']} {symbol} pominięty (otwarta pozycja)")
            rejected_open_pos += 1
            _emit_opportunity(
                strategy=signal.get("strategy", "crypto-momentum"),
                symbol=symbol, signal_state="REJECT",
                rsi=signal.get("rsi"), raw_signal=signal,
                gate_decisions=[{"gate": "risk", "decision": "BLOCK",
                                 "reason": "duplicate_position"}],
                rejection_reasons=["duplicate_position"],
                paper_action="rejected",
            )
            continue
        candidates.append(signal)

    print(f"  Scan summary: {scanned} coins; {len(candidates)} candidates; "
          f"rejected: no_signal={rejected_no_signal}, "
          f"alt_cap={rejected_alt_cap}, open_position={rejected_open_pos}")
    print(f"  BTC dominance proxy: btc_1h_change={btc_1h_change:+.2f}% " if btc_1h_change is not None
          else "  BTC dominance: unavailable")

    if not candidates:
        print(f"  No candidates after filters — quiet scan")
        _diag("crypto-monitor", DIAG_NO_SIGNAL,
              {"scanned": scanned, "rejected_no_signal": rejected_no_signal,
               "rejected_alt_cap": rejected_alt_cap,
               "rejected_open_pos": rejected_open_pos})
        notify_summary("Crypto Monitor", 0, 0)
        return
    _diag("crypto-monitor", DIAG_SIGNAL_DETECTED,
          {"candidates": len(candidates), "scanned": scanned})

    # ── Phase 2: optional LLM Curator filter ──
    candidates = _maybe_curate(candidates, account, btc_1h_change)
    if not candidates:
        print(f"  Curator rejected all candidates — no entries this scan")
        notify_summary("Crypto Monitor", 0, 0)
        return

    # ── Phase 3: emit (max 3 per run — predator philosophy: quality over volume) ──
    # v3.14.0 (2026-06-02) — wire confidence_inputs (closes CONF-002).
    try:
        from confidence_builder import build_confidence_inputs as _build_ci
    except ImportError:
        try:
            from shared.confidence_builder import build_confidence_inputs as _build_ci  # type: ignore
        except ImportError:
            def _build_ci(**_kw):  # type: ignore
                return None

    # v3.17.0 (2026-06-04) — feedback modules helper (Task 5).
    # NOTE: crypto skips lead_lag (no equity index analog). instrument_profile
    # may return insufficient_data for crypto pairs (Alpaca stocks-bars
    # endpoint doesn't serve crypto) — that's expected fail-soft behavior.
    try:
        from feedback_modules_helper import build_feedback_confidence_context as _build_feedback_ctx
    except ImportError:
        try:
            from shared.feedback_modules_helper import build_feedback_confidence_context as _build_feedback_ctx  # type: ignore
        except ImportError:
            def _build_feedback_ctx(**_kw):  # type: ignore
                return {}

    def _primary_score_for(strategy_name: str, rsi_val: float | None) -> float | None:
        if rsi_val is None:
            return None
        if strategy_name == "crypto-momentum":
            return max(0.0, min(1.0, (rsi_val - 50.0) / 30.0))      # RSI 50→0, 80→1
        if strategy_name == "crypto-oversold-bounce":
            return max(0.0, min(1.0, (35.0 - rsi_val) / 35.0))      # RSI 0→1, 35→0
        if strategy_name == "crypto-breakdown":
            return max(0.0, min(1.0, (50.0 - rsi_val) / 30.0))      # RSI 20→1, 50→0
        return 0.5

    alerts_sent = 0
    for signal in candidates[:3]:
        new_size = round(signal["size_usd"] * size_mult)
        ok, combined = concentration_ok(signal["symbol"], new_size, equity=equity)
        if not ok:
            print(f"  >>> {signal['action']} {signal['symbol']} pominięty "
                  f"(concentration {combined:.1f}% > 40%)")
            _emit_opportunity(
                strategy=signal.get("strategy", "crypto-momentum"),
                symbol=signal["symbol"], signal_state="REJECT",
                rsi=signal.get("rsi"), raw_signal=signal,
                gate_decisions=[{"gate": "risk", "decision": "BLOCK",
                                 "reason": f"concentration "
                                           f"{combined:.1f}% > 40%"}],
                rejection_reasons=[f"concentration:{combined:.1f}"],
                paper_action="rejected",
            )
            continue
        signal["size_usd"] = new_size
        # v3.14.0 — populate confidence_inputs for risk_officer gate
        # v3.17.0 — extend with feedback ctx (sweep + instrument profile;
        # lead_lag intentionally skipped — no equity index analog for crypto).
        try:
            fb_ctx = _build_feedback_ctx(
                symbol=signal.get("symbol", ""),
                bars=None,             # crypto signals don't carry bars dict
                index_closes=None,     # SKIP lead_lag for crypto
            )
        except Exception:
            fb_ctx = {}
        try:
            signal["confidence_inputs"] = _build_ci(
                strategy=signal.get("strategy", "crypto-momentum"),
                primary_score=_primary_score_for(signal.get("strategy", ""),
                                                  signal.get("rsi")),
                bars_count=24,                # 1h x 24 bars analyzed
                regime="NEUTRAL",             # crypto is regime-agnostic (24/7)
                account_status=account,
                **fb_ctx,
            )
        except Exception as _ci_e:
            print(f"  confidence_inputs build failed (non-fatal): {type(_ci_e).__name__}")
        print(f"  >>> SYGNAŁ: {signal['action']} {signal['symbol']}! "
              f"size=${new_size} concentration={combined:.1f}%")
        _diag("crypto-monitor", DIAG_EMIT_ATTEMPTED,
              {"symbol": signal.get("symbol"),
               "strategy": signal.get("strategy", "crypto-momentum")})
        sent = send_alert(signal)
        if sent:
            alerts_sent += 1
            _diag("crypto-monitor", DIAG_EMIT_SUCCESS,
                  {"symbol": signal.get("symbol")})
            _emit_opportunity(
                strategy=signal.get("strategy", "crypto-momentum"),
                symbol=signal["symbol"], signal_state="APPROVE",
                rsi=signal.get("rsi"), raw_signal=signal,
                confidence_inputs=signal.get("confidence_inputs"),
                gate_decisions=[{"gate": "risk", "decision": "PASS",
                                 "reason": "executed_via_alpaca"}],
                paper_action="executed",
                audit_link=f"alpaca:order:{signal['symbol'].replace('/', '')}",
            )
        else:
            _diag("crypto-monitor", DIAG_EMIT_FAILED,
                  {"symbol": signal.get("symbol"),
                   "reason": "alpaca_reject_or_deferred"})
            _emit_opportunity(
                strategy=signal.get("strategy", "crypto-momentum"),
                symbol=signal["symbol"], signal_state="REJECT",
                rsi=signal.get("rsi"), raw_signal=signal,
                confidence_inputs=signal.get("confidence_inputs"),
                gate_decisions=[{"gate": "risk", "decision": "BLOCK",
                                 "reason": "alpaca_reject_or_deferred"}],
                rejection_reasons=["alpaca_reject_or_deferred"],
                paper_action="rejected",
            )
        # Pass reason so notify subject shows [DEFERRED] / [NOT-SENT] instead
        # of "[SELL]" with generic "Alert NOT sent (error)" body.
        notify_signal(signal, sent, reason="" if sent else "alpaca_reject")

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
    _summary = run_scan()
    # v3.13.3 (2026-06-02) — heartbeat ping (READINESS-1 from backlog).
    # Fail-soft: ANY error here must NOT crash the monitor.
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "shared"))
        from heartbeat import ping as _hb_ping
        _hb_ping("crypto-monitor", status="ok",
                 message=f"scanned {(_summary or {}).get('scanned', 11)} coins")
    except Exception as _hb_e:
        print(f"  heartbeat ping failed (non-fatal): {type(_hb_e).__name__}")
