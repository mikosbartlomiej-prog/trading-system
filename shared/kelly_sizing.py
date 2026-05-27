"""shared/kelly_sizing.py — quarter-Kelly fraction sizing per strategy.

v3.11 (2026-05-27): replace fixed-size allocations with edge-proportional
position sizing. Strategies with stronger observed edge get more capital;
weaker strategies get less.

FORMULA (Kelly criterion):
    f* = (p × b - q) / b
    where:
      p = win probability (observed win_rate, 0-1)
      q = 1 - p (loss probability)
      b = win/loss payoff ratio (avg_win_pct / |avg_loss_pct|)

SAFETY:
- Quarter-Kelly: multiply f* by 0.25 (Kelly is volatile; full Kelly often
  produces ruinous drawdowns even when edge is real)
- Minimum sample: ≥10 closed trades before Kelly applies (under-sampled
  estimates are unreliable; falls back to base_size)
- Hard cap: f* clamped to [0, 0.5] before quarter-Kelly multiplier
- Floor: never below 0.10 × base_size (prevents tiny positions that
  pay $0 commission but tie up attention)
- Ceiling: never above 2.0 × base_size (prevents single strategy
  consuming all capital)

INTERPRETATION:
- Strategy with 70% WR, 1.5 R:R → f = (0.7×1.5 - 0.3) / 1.5 = 0.50 → ×0.25 = 0.125 → 12.5% equity
- Strategy with 50% WR, 1.0 R:R → f = 0 → falls back to base_size
- Strategy with 40% WR, 1.0 R:R → negative f → falls back to base (no
  capital). Edge gate (Phase A) should have already disabled this strategy.

USAGE:
    from kelly_sizing import compute_kelly_size

    size = compute_kelly_size(
        strategy_name="momentum-long",
        strategy_stats={"trades_lifetime": 25, "win_rate_lifetime": 0.65,
                        "pnl_usd_lifetime": 3500},  # OR pass per-trade history
        equity=100000,
        base_size_usd=15000,
    )
"""

from __future__ import annotations

import os
from typing import Optional


# Tunable via env
KELLY_SAFETY_FRACTION = float(os.environ.get("KELLY_SAFETY", "0.25"))  # quarter-Kelly
KELLY_MIN_SAMPLE = int(os.environ.get("KELLY_MIN_SAMPLE", "10"))
KELLY_MIN_RATIO = float(os.environ.get("KELLY_MIN_RATIO", "0.10"))  # floor
KELLY_MAX_RATIO = float(os.environ.get("KELLY_MAX_RATIO", "2.0"))   # ceiling


def _kelly_fraction(win_rate: float, payoff_ratio: float) -> float:
    """Pure Kelly f*. Clamp to [0, 0.5] before safety multiplier applies."""
    if payoff_ratio <= 0:
        return 0.0
    f = (win_rate * payoff_ratio - (1 - win_rate)) / payoff_ratio
    return max(0.0, min(0.5, f))


def compute_kelly_size(
    strategy_name: str,
    strategy_stats: dict,
    equity: float,
    base_size_usd: float,
    *,
    safety: Optional[float] = None,
) -> tuple[float, str]:
    """
    Returns (recommended_size_usd, reason).

    `reason` describes the decision path (audit-friendly).
    """
    safety = safety if safety is not None else KELLY_SAFETY_FRACTION

    # Minimum sample check
    n_trades = int(strategy_stats.get("trades_lifetime") or 0)
    if n_trades < KELLY_MIN_SAMPLE:
        return (base_size_usd,
                f"kelly: insufficient sample n={n_trades} < {KELLY_MIN_SAMPLE} "
                f"→ fall back to base ${base_size_usd:,.0f}")

    win_rate = float(strategy_stats.get("win_rate_lifetime") or 0)
    if win_rate <= 0:
        return (base_size_usd, "kelly: win_rate=0 → base size (likely no trade history yet)")

    # Payoff ratio: prefer explicit avg_win/avg_loss; fallback to assuming 1.0
    avg_win = float(strategy_stats.get("avg_win_pct") or 0)
    avg_loss = abs(float(strategy_stats.get("avg_loss_pct") or 0))

    if avg_win <= 0 or avg_loss <= 0:
        # Estimate from total P&L + win_rate (rough but workable)
        pnl = float(strategy_stats.get("pnl_usd_lifetime") or 0)
        n_wins = win_rate * n_trades
        n_losses = (1 - win_rate) * n_trades
        if pnl > 0 and n_wins > 0 and n_losses > 0:
            # If profitable, assume payoff ≥ 1; back-solve approximately
            # Pure heuristic: 1.5 default for profitable, 1.0 otherwise
            payoff = 1.5
        else:
            payoff = 1.0
    else:
        payoff = avg_win / avg_loss

    f_full = _kelly_fraction(win_rate, payoff)
    if f_full <= 0:
        return (base_size_usd,
                f"kelly: f*={f_full:.3f} (WR={win_rate:.0%}, payoff={payoff:.2f}) "
                f"= negative edge → base size (edge_validator should disable)")

    f_safe = f_full * safety
    raw_size = equity * f_safe

    # Floor + ceiling against base_size
    min_size = base_size_usd * KELLY_MIN_RATIO
    max_size = base_size_usd * KELLY_MAX_RATIO
    clamped = max(min_size, min(max_size, raw_size))

    ratio_to_base = clamped / base_size_usd
    return (
        clamped,
        f"kelly: f*={f_full:.3f}, quarter-Kelly={f_safe:.3f}, "
        f"raw=${raw_size:,.0f}, clamped=${clamped:,.0f} ({ratio_to_base:.1f}× base) "
        f"[WR={win_rate:.0%}, payoff={payoff:.2f}, n={n_trades}]"
    )
