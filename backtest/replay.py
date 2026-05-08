"""
Walk-forward replay for momentum strategies on daily bars.

Algorithm:
  for each day (after the warmup window):
    1. close any existing position if SL or TP hit during that day's range
    2. if no position open, evaluate signal at this bar's close
    3. if signal: open simulated position at close

Bookkeeping: trade list with (open_date, close_date, entry, exit,
direction, P&L $, P&L %, hold_days, exit_reason).

Notes:
  - One position at a time per (ticker, strategy). No overlapping entries.
  - Bracket simulated by checking next-day's high/low against TP/SL.
  - No slippage / commissions modelled — paper baseline only.
  - Position size = $10k per trade (matches strategies/aggressive-momentum.md).
"""

from typing import Callable, Optional


POSITION_SIZE_USD = 10_000.0


def replay(bars: dict,
            signal_fn: Callable[[int, dict], Optional[dict]],
            ticker: str = "?") -> dict:
    """
    Replay `signal_fn` over `bars` returning the trade ledger + summary.
    """
    closes  = bars["close"]
    highs   = bars["high"]
    lows    = bars["low"]
    times   = bars["time"]
    n       = len(closes)

    trades: list[dict] = []
    open_pos: Optional[dict] = None

    for idx in range(n):
        # 1) Close any open position if its SL/TP hit between yesterday's
        #    close and today's bar (we use today's high/low as the proxy).
        if open_pos is not None and idx > open_pos["entry_idx"]:
            day_high = highs[idx]
            day_low  = lows[idx]
            sl       = open_pos["stop_loss"]
            tp       = open_pos["take_profit"]
            direction = open_pos["direction"]

            exit_reason: Optional[str] = None
            exit_price: Optional[float] = None
            # Long: SL below entry, TP above. Bar must touch the level.
            if direction == "long":
                if day_low <= sl:
                    exit_price, exit_reason = sl, "SL"
                elif day_high >= tp:
                    exit_price, exit_reason = tp, "TP"
            else:  # short
                if day_high >= sl:
                    exit_price, exit_reason = sl, "SL"
                elif day_low <= tp:
                    exit_price, exit_reason = tp, "TP"

            if exit_reason:
                qty = POSITION_SIZE_USD / open_pos["entry_price"]
                if direction == "long":
                    pnl_usd = (exit_price - open_pos["entry_price"]) * qty
                    pnl_pct = (exit_price / open_pos["entry_price"] - 1) * 100
                else:
                    pnl_usd = (open_pos["entry_price"] - exit_price) * qty
                    pnl_pct = (1 - exit_price / open_pos["entry_price"]) * 100
                trades.append({
                    "ticker":       ticker,
                    "strategy":     open_pos["strategy"],
                    "direction":    direction,
                    "entry_date":   open_pos["entry_date"],
                    "exit_date":    times[idx],
                    "entry_price":  open_pos["entry_price"],
                    "exit_price":   exit_price,
                    "stop_loss":    sl,
                    "take_profit":  tp,
                    "pnl_usd":      round(pnl_usd, 2),
                    "pnl_pct":      round(pnl_pct, 2),
                    "hold_days":    idx - open_pos["entry_idx"],
                    "exit_reason":  exit_reason,
                    "winner":       pnl_usd > 0,
                })
                open_pos = None

        # 2) Evaluate signal at today's close (only if no open position)
        if open_pos is None:
            sig = signal_fn(idx, bars)
            if sig:
                direction = "long" if sig["action"] == "BUY" else "short"
                open_pos = {
                    "entry_idx":    idx,
                    "entry_date":   times[idx],
                    "entry_price":  sig["entry_price"],
                    "stop_loss":    sig["stop_loss"],
                    "take_profit":  sig["take_profit"],
                    "direction":    direction,
                    "strategy":     sig["strategy"],
                }

    # If still open at end of window — record as unrealized
    open_at_end = None
    if open_pos is not None:
        last_close = closes[-1]
        qty = POSITION_SIZE_USD / open_pos["entry_price"]
        if open_pos["direction"] == "long":
            unreal = (last_close - open_pos["entry_price"]) * qty
            unreal_pct = (last_close / open_pos["entry_price"] - 1) * 100
        else:
            unreal = (open_pos["entry_price"] - last_close) * qty
            unreal_pct = (1 - last_close / open_pos["entry_price"]) * 100
        open_at_end = {
            **open_pos,
            "unrealized_usd": round(unreal, 2),
            "unrealized_pct": round(unreal_pct, 2),
        }

    return {
        "ticker":      ticker,
        "trades":      trades,
        "open_at_end": open_at_end,
        "summary":     summarize(trades),
    }


def summarize(trades: list[dict]) -> dict:
    """Aggregate stats over a list of closed trades."""
    if not trades:
        return {
            "n_trades":       0,
            "wins":           0,
            "losses":         0,
            "win_rate":       0.0,
            "total_pnl_usd":  0.0,
            "avg_pnl_pct":    0.0,
            "best_pct":       0.0,
            "worst_pct":      0.0,
            "avg_hold_days":  0.0,
        }
    wins   = [t for t in trades if t["winner"]]
    losses = [t for t in trades if not t["winner"]]
    pcts   = [t["pnl_pct"] for t in trades]
    return {
        "n_trades":       len(trades),
        "wins":           len(wins),
        "losses":         len(losses),
        "win_rate":       round(len(wins) / len(trades), 3),
        "total_pnl_usd":  round(sum(t["pnl_usd"] for t in trades), 2),
        "avg_pnl_pct":    round(sum(pcts) / len(pcts), 2),
        "best_pct":       round(max(pcts), 2),
        "worst_pct":      round(min(pcts), 2),
        "avg_hold_days":  round(sum(t["hold_days"] for t in trades) / len(trades), 1),
    }
