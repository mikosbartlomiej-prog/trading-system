"""
Backtest realism: slippage, gap risk, missed runs, costs, richer metrics.

Wraps the existing backtest/replay.py logic without modifying it. The
new entry point `replay_with_realism()` accepts a `RealismConfig` so
callers can dial slippage / gap-penalty / missed-run probability per
asset class.

Why a wrapper instead of refactoring replay.py:
  - replay.py is well-tested at the basic level (smoke test landed
    2026-05-08); rewriting risks regressions.
  - Realism options are advisory — the basic harness still makes sense
    for "is this strategy directional alpha alive?" questions.
  - Tests can compare both paths to prove realism only ever worsens
    outcomes (monotonicity check in tests/architecture_vnext).

Public functions:
    apply_entry_slippage(price, direction, config)
    apply_exit_slippage(price, direction, exit_reason, config)
    gap_penalty(stop_price, gap_proxy, direction)
    should_skip_run(idx, config, seed=42)
    compute_rich_metrics(trades)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional


# ─── Configuration ────────────────────────────────────────────────────────────

@dataclass
class RealismConfig:
    """
    All fractions, not percent.

    slippage_bps:      basis points (5 bps = 0.05%) — for stocks
    slippage_bps_crypto: higher for crypto (default 20 bps)
    slippage_bps_options: even higher (default 50 bps)
    gap_penalty_pct:   when SL fires, simulate gap-through slippage —
                       the fill is `stop * (1 - gap_penalty_pct)` for
                       longs and `stop * (1 + gap_penalty_pct)` for shorts.
                       Models the case where the bar opens below your stop
                       on a long and you fill at open, not stop.
    missed_run_pct:    probability that a given bar's signal is skipped
                       (simulates GitHub Actions failures, runner unhealthy,
                       etc.). 0.0 to disable.
    cost_per_trade_usd: round-trip cost in USD (commission proxy).
                       Paper Alpaca has $0, but factor in any wrapper costs.
    """
    slippage_bps:         float = 8.0
    slippage_bps_crypto:  float = 25.0
    slippage_bps_options: float = 60.0
    gap_penalty_pct:      float = 0.005     # 0.5%
    missed_run_pct:       float = 0.0
    cost_per_trade_usd:   float = 0.0
    seed:                 int   = 42


def _bps(config: RealismConfig, asset_class: str) -> float:
    return {
        "crypto":    config.slippage_bps_crypto,
        "us_option": config.slippage_bps_options,
    }.get(asset_class, config.slippage_bps)


# ─── Slippage primitives ──────────────────────────────────────────────────────

def apply_entry_slippage(price: float, direction: str,
                         config: RealismConfig,
                         asset_class: str = "us_equity") -> float:
    """
    Worsen the fill on entry by `slippage_bps`. Longs pay more, shorts get less.
    """
    bps = _bps(config, asset_class)
    fraction = bps / 10_000.0
    if direction == "long":
        return price * (1 + fraction)
    return price * (1 - fraction)


def apply_exit_slippage(price: float, direction: str,
                        config: RealismConfig,
                        asset_class: str = "us_equity") -> float:
    """
    Worsen the fill on exit. Longs sell for less, shorts cover for more.
    """
    bps = _bps(config, asset_class)
    fraction = bps / 10_000.0
    if direction == "long":
        return price * (1 - fraction)
    return price * (1 + fraction)


def gap_penalty(stop_price: float, direction: str,
                config: RealismConfig) -> float:
    """
    Worse-than-stop fill. Used for SL exits where the bar gapped through
    the level and you couldn't fill at the stop.
    """
    pct = config.gap_penalty_pct
    if direction == "long":
        # Long stops are below entry; gap takes you below the stop.
        return stop_price * (1 - pct)
    return stop_price * (1 + pct)


# ─── Missed-run simulation ────────────────────────────────────────────────────

def should_skip_run(idx: int, config: RealismConfig,
                    salt: str = "backtest") -> bool:
    """
    Deterministic skip decision based on (idx, seed, salt). Same seed +
    same bar idx → same answer. Lets us run reproducible experiments
    while still injecting GH Actions failures into the simulation.
    """
    if config.missed_run_pct <= 0:
        return False
    if config.missed_run_pct >= 1:
        return True
    h = hashlib.sha1(f"{salt}:{config.seed}:{idx}".encode()).digest()
    # First 4 bytes → uint32 → 0..1
    n = int.from_bytes(h[:4], "big") / (2**32)
    return n < config.missed_run_pct


# ─── Rich metrics ─────────────────────────────────────────────────────────────

def compute_rich_metrics(trades: list[dict]) -> dict:
    """
    Beyond basic win-rate / total P&L:

      profit_factor   = sum(wins) / abs(sum(losses))
      expectancy_usd  = mean P&L per trade
      avg_win_usd     = mean winners
      avg_loss_usd    = mean losers (negative)
      max_drawdown_usd
      max_drawdown_pct (of peak equity)
      worst_trade_pct
      best_trade_pct
      avg_hold_days
      turnover (trades per 252 days)
      tp_hit_rate     = % of trades where exit_reason=="TP"
    """
    if not trades:
        return {
            "n_trades": 0, "profit_factor": 0.0, "expectancy_usd": 0.0,
            "avg_win_usd": 0.0, "avg_loss_usd": 0.0,
            "max_drawdown_usd": 0.0, "max_drawdown_pct": 0.0,
            "worst_trade_pct": 0.0, "best_trade_pct": 0.0,
            "avg_hold_days": 0.0, "tp_hit_rate": 0.0,
            "fill_rate": 1.0,
        }
    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    sum_win = sum(t["pnl_usd"] for t in wins)
    sum_loss = sum(t["pnl_usd"] for t in losses)  # negative
    pcts = [t.get("pnl_pct", 0.0) for t in trades]

    # Running equity to compute max drawdown
    equity = 0.0
    peak = 0.0
    dd_usd = 0.0
    for t in trades:
        equity += t["pnl_usd"]
        if equity > peak:
            peak = equity
        else:
            dd_usd = min(dd_usd, equity - peak)  # negative
    dd_pct = (dd_usd / peak * 100.0) if peak > 0 else 0.0

    tp_count = sum(1 for t in trades if t.get("exit_reason") == "TP")
    fill_count = sum(1 for t in trades if t.get("filled", True))

    return {
        "n_trades":         len(trades),
        "wins":             len(wins),
        "losses":           len(losses),
        "win_rate":         round(len(wins) / len(trades), 3),
        "total_pnl_usd":    round(sum(t["pnl_usd"] for t in trades), 2),
        "profit_factor":    round(sum_win / abs(sum_loss), 3) if sum_loss != 0 else float("inf"),
        "expectancy_usd":   round(sum(t["pnl_usd"] for t in trades) / len(trades), 2),
        "avg_win_usd":      round(sum_win / len(wins), 2) if wins else 0.0,
        "avg_loss_usd":     round(sum_loss / len(losses), 2) if losses else 0.0,
        "max_drawdown_usd": round(dd_usd, 2),
        "max_drawdown_pct": round(dd_pct, 2),
        "best_trade_pct":   round(max(pcts), 2) if pcts else 0.0,
        "worst_trade_pct":  round(min(pcts), 2) if pcts else 0.0,
        "avg_hold_days":    round(sum(t.get("hold_days", 0)
                                       for t in trades) / len(trades), 1),
        "tp_hit_rate":      round(tp_count / len(trades), 3),
        "fill_rate":        round(fill_count / max(1, len(trades)), 3),
        "turnover":         round(len(trades) / max(1, len(trades)) * 252, 1),
    }


# ─── Realistic replay wrapper ─────────────────────────────────────────────────

def replay_with_realism(
    bars: dict,
    signal_fn: Callable,
    ticker: str = "?",
    config: Optional[RealismConfig] = None,
    asset_class: str = "us_equity",
    position_size_usd: float = 10_000.0,
) -> dict:
    """
    Walk-forward replay with slippage / gap / missed-runs / costs.

    Returns dict with keys: ticker, trades, summary, realism_config.
    """
    config = config or RealismConfig()
    closes = bars["close"]
    highs  = bars["high"]
    lows   = bars["low"]
    times  = bars["time"]
    n = len(closes)

    trades: list[dict] = []
    open_pos: Optional[dict] = None

    for idx in range(n):
        # 1) exit logic
        if open_pos is not None and idx > open_pos["entry_idx"]:
            day_high = highs[idx]
            day_low  = lows[idx]
            sl = open_pos["stop_loss"]
            tp = open_pos["take_profit"]
            direction = open_pos["direction"]

            exit_reason: Optional[str] = None
            exit_price: Optional[float] = None
            if direction == "long":
                if day_low <= sl:
                    # Gap penalty: fill below stop on a long
                    exit_price = gap_penalty(sl, direction, config)
                    exit_reason = "SL"
                elif day_high >= tp:
                    exit_price = apply_exit_slippage(tp, direction, config, asset_class)
                    exit_reason = "TP"
            else:  # short
                if day_high >= sl:
                    exit_price = gap_penalty(sl, direction, config)
                    exit_reason = "SL"
                elif day_low <= tp:
                    exit_price = apply_exit_slippage(tp, direction, config, asset_class)
                    exit_reason = "TP"

            if exit_reason:
                qty = position_size_usd / open_pos["entry_price"]
                if direction == "long":
                    pnl_usd = (exit_price - open_pos["entry_price"]) * qty
                    pnl_pct = (exit_price / open_pos["entry_price"] - 1) * 100
                else:
                    pnl_usd = (open_pos["entry_price"] - exit_price) * qty
                    pnl_pct = (1 - exit_price / open_pos["entry_price"]) * 100
                pnl_usd -= config.cost_per_trade_usd
                trades.append({
                    "ticker":      ticker,
                    "strategy":    open_pos["strategy"],
                    "direction":   direction,
                    "entry_date":  open_pos["entry_date"],
                    "exit_date":   times[idx],
                    "entry_price": round(open_pos["entry_price"], 4),
                    "exit_price":  round(exit_price, 4),
                    "stop_loss":   sl,
                    "take_profit": tp,
                    "pnl_usd":     round(pnl_usd, 2),
                    "pnl_pct":     round(pnl_pct, 2),
                    "hold_days":   idx - open_pos["entry_idx"],
                    "exit_reason": exit_reason,
                    "winner":      pnl_usd > 0,
                    "filled":      True,
                })
                open_pos = None

        # 2) entry logic
        if open_pos is None:
            if should_skip_run(idx, config, salt=f"{ticker}-{asset_class}"):
                # Pretend the cron run was skipped — no signal evaluation
                continue
            sig = signal_fn(idx, bars)
            if sig:
                direction = "long" if sig["action"] == "BUY" else "short"
                entry_with_slip = apply_entry_slippage(
                    sig["entry_price"], direction, config, asset_class
                )
                open_pos = {
                    "entry_idx":   idx,
                    "entry_date":  times[idx],
                    "entry_price": entry_with_slip,
                    "stop_loss":   sig["stop_loss"],
                    "take_profit": sig["take_profit"],
                    "direction":   direction,
                    "strategy":    sig["strategy"],
                }

    return {
        "ticker":          ticker,
        "trades":          trades,
        "summary":         compute_rich_metrics(trades),
        "realism_config":  config.__dict__,
        "asset_class":     asset_class,
    }
