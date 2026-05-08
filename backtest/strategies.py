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
"""

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
