"""
Pure-function signal logic extracted from the live monitors so it can be
replayed against historical bars.

Each `*_signal_at(day_idx, bars)` function looks at the trailing window
ending at `bars[..day_idx]` (inclusive) and returns either:
  - None: no signal
  - dict: {action, entry_price, stop_loss, take_profit, strategy}

Key contract: these functions read ONLY the bars passed in. No I/O, no
external calls. Lets `replay.py` iterate the timeline cleanly.

Constants mirror the live `price-monitor/monitor.py` (ATR-based SL/TP
multipliers from STRATEGY.md §4.1-4.2).

v3.16 (2026-06-04) — added crypto signal functions ported from the live
crypto-monitor:
  - crypto_momentum_signal_at:        predator-momentum breakout entry
  - crypto_oversold_bounce_signal_at: deep-oversold mean-reversion entry

Both are pure — they read ONLY `bars[:idx+1]`. The live monitor's
optional BTC-dominance guard is exposed as an optional kwarg through
the registry-friendly wrapper functions below; default is inactive
(backtest does not have a per-tick BTC-1h-change feed unless we run
BTC as the dominant ticker in parallel).
"""

from __future__ import annotations

from typing import Optional


# Tunables — STRICT variant must match price-monitor / STRATEGY.md
ATR_SL_MULT      = 2.0
ATR_TP_MULT      = 4.0
RSI_LONG_MIN     = 50
RSI_LONG_MAX     = 70
RSI_SHORT_MIN    = 72
VOLUME_MULT_LONG = 1.5
VOLUME_MULT_SHORT_MAX = 0.8
LOOKBACK_DAYS    = 20

# LOOSE variant — research/backtest only, not wired into live monitor.
# Hypothesis: relaxing RSI band to 45-75 + volume to 1.2× increases
# trade frequency without killing win rate. Validated empirically vs
# the strict baseline (3 trades / 67% WR / +$1,595 over 180 d on 9
# mega-cap basket — see backtest results 2026-05-08).
LOOSE_RSI_LONG_MIN     = 45
LOOSE_RSI_LONG_MAX     = 75
LOOSE_VOLUME_MULT_LONG = 1.2


def _rsi(closes: list[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains  = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _atr(highs: list[float], lows: list[float], closes: list[float],
         period: int = 14) -> Optional[float]:
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


def _momentum_long_signal_with_params(idx: int, bars: dict,
                                        rsi_min: float, rsi_max: float,
                                        vol_mult: float) -> Optional[dict]:
    """Internal — parametric momentum-long. Used by strict + loose variants."""
    if idx < 22:                              # need 20-day window + RSI
        return None
    closes  = bars["close"][:idx + 1]
    highs   = bars["high"][:idx + 1]
    lows    = bars["low"][:idx + 1]
    volumes = bars["volume"][:idx + 1]

    cur     = closes[-1]
    cur_vol = volumes[-1]
    high_20 = max(highs[-21:-1])
    avg_vol = sum(volumes[-21:-1]) / 20.0
    rsi     = _rsi(closes)
    atr     = _atr(highs, lows, closes) or (cur * 0.02)

    if cur <= high_20:
        return None
    if cur_vol <= avg_vol * vol_mult:
        return None
    if rsi is None or not (rsi_min <= rsi <= rsi_max):
        return None

    return {
        "action":      "BUY",
        "strategy":    "momentum-long",
        "entry_price": round(cur, 2),
        "stop_loss":   round(cur - ATR_SL_MULT * atr, 2),
        "take_profit": round(cur + ATR_TP_MULT * atr, 2),
        "rsi":         round(rsi, 1),
        "atr":         round(atr, 2),
    }


def momentum_long_signal_at(idx: int, bars: dict) -> Optional[dict]:
    """
    STRICT momentum-long (matches live `price-monitor/monitor.py`):
      1. close > 20-day high (breakout)
      2. volume > 1.5 x 20-day avg volume
      3. RSI(14) in [50, 70]
    """
    return _momentum_long_signal_with_params(
        idx, bars,
        rsi_min=RSI_LONG_MIN, rsi_max=RSI_LONG_MAX,
        vol_mult=VOLUME_MULT_LONG,
    )


def momentum_long_loose_signal_at(idx: int, bars: dict) -> Optional[dict]:
    """
    LOOSE momentum-long — backtest-only variant for filter sensitivity
    research. Same shape as strict but with relaxed thresholds:
      - RSI band 45-75 (was 50-70)
      - volume 1.2× avg (was 1.5×)
    Use to test whether the strict filter is over-restrictive.
    """
    return _momentum_long_signal_with_params(
        idx, bars,
        rsi_min=LOOSE_RSI_LONG_MIN, rsi_max=LOOSE_RSI_LONG_MAX,
        vol_mult=LOOSE_VOLUME_MULT_LONG,
    )


def overbought_short_signal_at(idx: int, bars: dict) -> Optional[dict]:
    """
    Returns a short entry proposal if at bar `idx`:
      1. RSI(14) > 72 (overbought)
      2. AND 2-of-3 weakening: price within 2% of 20d high, volume below
         0.8 x avg, close < prior open.

    Otherwise None.
    """
    if idx < 22:
        return None
    closes  = bars["close"][:idx + 1]
    highs   = bars["high"][:idx + 1]
    lows    = bars["low"][:idx + 1]
    opens   = bars["open"][:idx + 1]
    volumes = bars["volume"][:idx + 1]

    cur     = closes[-1]
    cur_vol = volumes[-1]
    high_20 = max(highs[-21:-1])
    avg_vol = sum(volumes[-21:-1]) / 20.0
    rsi     = _rsi(closes)
    atr     = _atr(highs, lows, closes) or (cur * 0.02)

    if rsi is None or rsi <= RSI_SHORT_MIN:
        return None

    weakening = 0
    if cur >= high_20 * 0.98:
        weakening += 1
    if cur_vol < avg_vol * VOLUME_MULT_SHORT_MAX:
        weakening += 1
    if len(opens) >= 2 and cur < opens[-2]:
        weakening += 1
    if weakening < 2:
        return None

    return {
        "action":      "SELL_SHORT",
        "strategy":    "overbought-short",
        "entry_price": round(cur, 2),
        "stop_loss":   round(cur + ATR_SL_MULT * atr, 2),
        "take_profit": round(cur - ATR_TP_MULT * atr, 2),
        "rsi":         round(rsi, 1),
        "atr":         round(atr, 2),
        "weakening_count": weakening,
    }


# ─── Crypto strategy constants (mirror crypto-monitor/monitor.py) ────────────
# Predator-momentum (crypto-momentum strategy) tunables.
CRYPTO_RSI_LONG_MIN          = 45.0
CRYPTO_RSI_LONG_MAX_DEFAULT  = 68.0      # Tier 1 default (BTC/ETH)
CRYPTO_VOL_MULT_DEFAULT      = 2.0       # Tier 1 default
CRYPTO_LOOKBACK_BARS         = 20        # 20-bar breakout window
CRYPTO_TP_PCT_DEFAULT        = 0.20      # +20% TP
CRYPTO_SL_PCT_DEFAULT        = 0.07      # -7%  SL
CRYPTO_MOMENTUM_24H_MIN_PCT  = 3.0       # predator floor
CRYPTO_MOMENTUM_24H_MAX_PCT  = 15.0      # predator ceiling
CRYPTO_BTC_DOMINANCE_GUARD   = -3.0      # Tier 2 alt-long blocker

# Oversold-bounce constants (v3.13.3 contract — 3-bar stabilization).
CRYPTO_OVERSOLD_RSI_MAX        = 30.0
CRYPTO_OVERSOLD_MIN_MOVE_PCT   = -10.0
CRYPTO_OVERSOLD_REVERSAL_BARS  = 3
CRYPTO_OVERSOLD_VOL_FLOOR      = 0.25    # × vol_mult
CRYPTO_OVERSOLD_SL_WIDEN       = 1.5     # 1.5× normal SL

# 24-hour move uses 24 × 1h bars
CRYPTO_24H_BARS = 24


def _crypto_24h_move_pct(closes: list[float]) -> Optional[float]:
    """Mirror of crypto-monitor calculate_24h_move_pct (pure)."""
    if len(closes) < CRYPTO_24H_BARS + 1:
        return None
    prev = closes[-(CRYPTO_24H_BARS + 1)]
    curr = closes[-1]
    if prev <= 0:
        return None
    return (curr - prev) / prev * 100.0


def _crypto_avg_vol_safe(volumes: list[float]) -> bool:
    """Avg-volume sanity (need enough non-zero bars)."""
    nonzero = [v for v in volumes[-(CRYPTO_LOOKBACK_BARS + 1):-1] if v > 0]
    return len(nonzero) >= 15


def crypto_momentum_signal_at(
    idx: int,
    bars: dict,
    *,
    rsi_long_max: float = CRYPTO_RSI_LONG_MAX_DEFAULT,
    vol_mult: float = CRYPTO_VOL_MULT_DEFAULT,
    tp_pct: float = CRYPTO_TP_PCT_DEFAULT,
    sl_pct: float = CRYPTO_SL_PCT_DEFAULT,
    btc_dominance_change: Optional[float] = None,
    is_tier_2: bool = False,
) -> Optional[dict]:
    """
    Predator-momentum LONG entry on 1h crypto bars.

    Filters (mirror crypto-monitor `check_crypto_signal` LONG branch):
      1. Need >= 25 bars (CRYPTO_LOOKBACK_BARS + 1 RSI warm-up + 24h move).
      2. price > 20-bar high (breakout).
      3. volume > vol_mult × 20-bar avg.
      4. RSI(14) in [45, rsi_long_max].
      5. PREDATOR: |24h_move| in [3%, 15%].
      6. BTC dominance guard (Tier 2 only) — if `btc_dominance_change`
         is given AND `is_tier_2` AND change <= -3% → blocked.

    Pure: reads `bars[:idx+1]` only.

    Returns the same shape as `momentum_long_signal_at` so the replay
    + realism harness can consume without changes.
    """
    if idx < 25:                                      # need 25 bars min
        return None

    closes  = bars["close"][:idx + 1]
    highs   = bars["high"][:idx + 1]
    lows    = bars["low"][:idx + 1]                     # noqa: F841 (kept for parity)
    volumes = bars["volume"][:idx + 1]

    if len(closes) < CRYPTO_LOOKBACK_BARS + 1:
        return None

    cur     = closes[-1]
    cur_vol = volumes[-1]
    high_20 = max(highs[-(CRYPTO_LOOKBACK_BARS + 1):-1])
    if _crypto_avg_vol_safe(volumes):
        avg_vol = sum(volumes[-(CRYPTO_LOOKBACK_BARS + 1):-1]) / CRYPTO_LOOKBACK_BARS
    else:
        return None
    if avg_vol <= 0:
        return None

    rsi = _rsi(closes)
    move_24h = _crypto_24h_move_pct(closes)

    # PREDATOR bracket on 24h move (absolute, like the live monitor).
    if move_24h is None:
        return None
    if not (CRYPTO_MOMENTUM_24H_MIN_PCT <= abs(move_24h) <= CRYPTO_MOMENTUM_24H_MAX_PCT):
        return None

    # Breakout + volume + RSI band
    if cur <= high_20:
        return None
    if cur_vol <= avg_vol * vol_mult:
        return None
    if rsi is None or not (CRYPTO_RSI_LONG_MIN <= rsi <= rsi_long_max):
        return None

    # BTC dominance guard for Tier 2
    if is_tier_2 and btc_dominance_change is not None \
            and btc_dominance_change <= CRYPTO_BTC_DOMINANCE_GUARD:
        return None

    return {
        "action":      "BUY",
        "strategy":    "crypto-momentum",
        "entry_price": round(cur, 4),
        "stop_loss":   round(cur * (1 - sl_pct), 4),
        "take_profit": round(cur * (1 + tp_pct), 4),
        "rsi":         round(rsi, 1),
        "move_24h_pct": round(move_24h, 2),
        "volume_ratio": round(cur_vol / avg_vol, 2),
        "tier":         2 if is_tier_2 else 1,
    }


def crypto_oversold_bounce_signal_at(
    idx: int,
    bars: dict,
    *,
    rsi_max: float = CRYPTO_OVERSOLD_RSI_MAX,
    min_move_pct: float = CRYPTO_OVERSOLD_MIN_MOVE_PCT,
    reversal_bars: int = CRYPTO_OVERSOLD_REVERSAL_BARS,
    vol_floor: float = CRYPTO_OVERSOLD_VOL_FLOOR,
    vol_mult: float = CRYPTO_VOL_MULT_DEFAULT,
    tp_pct: float = CRYPTO_TP_PCT_DEFAULT,
    sl_pct: float = CRYPTO_SL_PCT_DEFAULT,
    sl_widen: float = CRYPTO_OVERSOLD_SL_WIDEN,
    btc_dominance_change: Optional[float] = None,
    is_tier_2: bool = False,
) -> Optional[dict]:
    """
    Deep-oversold mean-reversion LONG entry on 1h crypto bars.

    Mirrors `crypto-monitor::check_crypto_signal` oversold-bounce branch
    (v3.13.3 — 3-bar stabilization, not strict 1-bar reversal).

    Filters (all must hold):
      1. >= reversal_bars + 1 bars available (default 4).
      2. RSI(14) <= rsi_max  (default 30 — deep oversold).
      3. 24h_move >= min_move_pct  (default -10% — not a catastrophe).
      4. STABILIZATION: avg(closes[-3:]) >= closes[-4]
         (3-bar average above the bar 3 hours ago — bleeding stopped).
      5. current_volume > avg_vol_20 × (vol_mult × vol_floor)
         (default 25% of vol_mult = some buying interest).
      6. BTC dominance guard (Tier 2 only).

    SL is `1 - sl_pct × sl_widen` (default 1.5× wider than predator SL).
    TP is `1 + tp_pct`.
    """
    if idx < max(25, reversal_bars + 1):
        return None

    closes  = bars["close"][:idx + 1]
    highs   = bars["high"][:idx + 1]                     # noqa: F841
    lows    = bars["low"][:idx + 1]                       # noqa: F841
    volumes = bars["volume"][:idx + 1]

    if len(closes) < reversal_bars + 1:
        return None

    cur     = closes[-1]
    cur_vol = volumes[-1]
    if _crypto_avg_vol_safe(volumes):
        avg_vol = sum(volumes[-(CRYPTO_LOOKBACK_BARS + 1):-1]) / CRYPTO_LOOKBACK_BARS
    else:
        return None
    if avg_vol <= 0:
        return None

    rsi = _rsi(closes)
    move_24h = _crypto_24h_move_pct(closes)

    if rsi is None or rsi > rsi_max:
        return None
    if move_24h is None or move_24h < min_move_pct:
        return None

    # Stabilization rule
    if len(closes) < 4:
        return None
    recent_avg = sum(closes[-3:]) / 3.0
    baseline = closes[-4]
    if recent_avg < baseline:
        return None

    # Volume floor
    if cur_vol <= avg_vol * (vol_mult * vol_floor):
        return None

    # BTC dominance guard for Tier 2
    if is_tier_2 and btc_dominance_change is not None \
            and btc_dominance_change <= CRYPTO_BTC_DOMINANCE_GUARD:
        return None

    return {
        "action":      "BUY",
        "strategy":    "crypto-oversold-bounce",
        "entry_price": round(cur, 4),
        "stop_loss":   round(cur * (1 - sl_pct * sl_widen), 4),
        "take_profit": round(cur * (1 + tp_pct), 4),
        "rsi":         round(rsi, 1),
        "move_24h_pct": round(move_24h, 2),
        "volume_ratio": round(cur_vol / avg_vol, 2),
        "tier":         2 if is_tier_2 else 1,
    }


__all__ = [
    "momentum_long_signal_at",
    "momentum_long_loose_signal_at",
    "overbought_short_signal_at",
    "crypto_momentum_signal_at",
    "crypto_oversold_bounce_signal_at",
    # constants exposed for tests / tuning
    "CRYPTO_RSI_LONG_MIN",
    "CRYPTO_RSI_LONG_MAX_DEFAULT",
    "CRYPTO_VOL_MULT_DEFAULT",
    "CRYPTO_MOMENTUM_24H_MIN_PCT",
    "CRYPTO_MOMENTUM_24H_MAX_PCT",
    "CRYPTO_OVERSOLD_RSI_MAX",
    "CRYPTO_OVERSOLD_MIN_MOVE_PCT",
    "CRYPTO_OVERSOLD_REVERSAL_BARS",
    "CRYPTO_OVERSOLD_VOL_FLOOR",
    "CRYPTO_OVERSOLD_SL_WIDEN",
    "CRYPTO_BTC_DOMINANCE_GUARD",
]
