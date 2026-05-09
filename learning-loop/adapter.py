"""
Adapter — pure function (old_state, today_stats) -> new_state.

Heuristics encoded as small testable functions. No I/O — analyzer.py
owns reading/writing files.
"""

from copy import deepcopy
from datetime import datetime, timezone


# ─── Bounds & thresholds ─────────────────────────────────────────────────────

MIN_SAMPLE_TRADES   = 10        # don't adapt until lifetime >= this many trades
MIN_7D_TRADES       = 5         # don't adapt 7d window until 5+ trades

MIN_SIZE_MULT       = 0.30
MAX_SIZE_MULT       = 2.00

# Win-rate triggers (over 7d window)
WR_COOL_THRESHOLD   = 0.35      # below this -> size *= 0.8
WR_WARM_THRESHOLD   = 0.60      # above this -> size *= 1.10

# P&L triggers (% of equity over 7d)
PL_COOL_PCT         = -2.0      # below this -> size *= 0.7
PL_WARM_PCT         =  3.0      # above this -> size *= 1.05

# Disable triggers
CONSECUTIVE_LOSS_LIMIT       = 5       # 5 in a row -> pause
LIFETIME_ROI_DISABLE_PCT     = -10.0   # lifetime ROI worse than this -> pause

# Pause duration in days (auto re-enable check after this)
PAUSE_DAYS = 3


# ─── Helper: apply multiplicative size change with bounds ────────────────────

def _adjust_size(current: float, factor: float) -> float:
    new = current * factor
    return max(MIN_SIZE_MULT, min(MAX_SIZE_MULT, new))


# ─── Per-strategy adaptation ─────────────────────────────────────────────────

def adapt_strategy(name: str, old: dict, stats: dict, equity: float) -> dict:
    """
    Compute new strategy state given:
      old:     prior state dict (or {} / partial dict if first run /
               manual edit). Missing keys get default values.
      stats:   today's contribution + 7d totals + lifetime totals
      equity:  current account equity (for P&L %)

    Returns a new dict with size_multiplier, enabled, side_bias, rationale,
    and rolled-up stats.
    """
    defaults = {
        "trades_lifetime":    0,
        "trades_7d":          0,
        "win_rate_lifetime":  0.0,
        "win_rate_7d":        0.0,
        "pnl_usd_lifetime":   0.0,
        "pnl_usd_7d":         0.0,
        "size_multiplier":    1.0,
        "enabled":            True,
        "side_bias":          None,
        "consecutive_losses": 0,
        "rationale":          "default",
        "paused_until":       None,
    }
    # Start from defaults, overlay any old keys present (defensive: handles
    # partial state.json after manual edit or first run).
    new = deepcopy(defaults)
    if old:
        for k, v in old.items():
            new[k] = v

    # Roll in the latest stats (analyzer computes these)
    new["trades_lifetime"]   = stats.get("trades_lifetime", new["trades_lifetime"])
    new["trades_7d"]         = stats.get("trades_7d", 0)
    new["win_rate_lifetime"] = stats.get("win_rate_lifetime", 0.0)
    new["win_rate_7d"]       = stats.get("win_rate_7d", 0.0)
    new["pnl_usd_lifetime"]  = stats.get("pnl_usd_lifetime", 0.0)
    new["pnl_usd_7d"]        = stats.get("pnl_usd_7d", 0.0)
    new["consecutive_losses"] = stats.get("consecutive_losses", 0)

    today_iso = datetime.now(timezone.utc).date().isoformat()

    # Auto-resume from pause if expired
    if new.get("paused_until"):
        if today_iso >= new["paused_until"]:
            new["enabled"] = True
            new["paused_until"] = None
            new["rationale"] = f"auto-resumed from pause on {today_iso}"

    # If currently paused, don't adapt size
    if not new["enabled"]:
        return new

    # Insufficient sample
    if new["trades_lifetime"] < MIN_SAMPLE_TRADES:
        new["rationale"] = (
            f"hold (lifetime trades {new['trades_lifetime']} < {MIN_SAMPLE_TRADES}; "
            f"need more sample before adapting)"
        )
        return new

    old_mult = new["size_multiplier"]
    reasons  = []

    # Lifetime ROI disable
    starting = stats.get("starting_equity", equity if equity > 0 else 100000)
    lifetime_roi = (new["pnl_usd_lifetime"] / starting * 100) if starting > 0 else 0.0
    if lifetime_roi < LIFETIME_ROI_DISABLE_PCT:
        new["enabled"] = False
        new["paused_until"] = (datetime.now(timezone.utc).date()).isoformat()
        new["rationale"] = (
            f"DISABLED — lifetime ROI {lifetime_roi:.1f}% < {LIFETIME_ROI_DISABLE_PCT}%; "
            f"manual review required (clear paused_until in state.json to re-enable)"
        )
        return new

    # Consecutive losses pause
    if new["consecutive_losses"] >= CONSECUTIVE_LOSS_LIMIT:
        from datetime import timedelta
        until = (datetime.now(timezone.utc).date() + timedelta(days=PAUSE_DAYS)).isoformat()
        new["enabled"] = False
        new["paused_until"] = until
        new["rationale"] = (
            f"PAUSED until {until} — {new['consecutive_losses']} consecutive losses; "
            f"auto-resume after {PAUSE_DAYS} days"
        )
        return new

    # Sample for 7d adjustments
    if new["trades_7d"] >= MIN_7D_TRADES:
        # Win rate thresholds
        if new["win_rate_7d"] < WR_COOL_THRESHOLD:
            new["size_multiplier"] = _adjust_size(new["size_multiplier"], 0.8)
            reasons.append(f"7d win-rate {new['win_rate_7d']*100:.0f}% < {WR_COOL_THRESHOLD*100:.0f}% -> -20%")
        elif new["win_rate_7d"] > WR_WARM_THRESHOLD:
            new["size_multiplier"] = _adjust_size(new["size_multiplier"], 1.10)
            reasons.append(f"7d win-rate {new['win_rate_7d']*100:.0f}% > {WR_WARM_THRESHOLD*100:.0f}% -> +10%")

        # P&L thresholds
        pl_pct = (new["pnl_usd_7d"] / equity * 100) if equity > 0 else 0
        if pl_pct < PL_COOL_PCT:
            new["size_multiplier"] = _adjust_size(new["size_multiplier"], 0.7)
            reasons.append(f"7d P&L {pl_pct:+.1f}% < {PL_COOL_PCT}% -> -30%")
        elif pl_pct > PL_WARM_PCT:
            new["size_multiplier"] = _adjust_size(new["size_multiplier"], 1.05)
            reasons.append(f"7d P&L {pl_pct:+.1f}% > {PL_WARM_PCT}% -> +5%")

    # Side-bias for options (if user opt-in via "options-momentum" name)
    # Heuristic: if strategy-options has separate long_pnl vs short_pnl tracked
    long_pnl  = stats.get("pnl_long_7d", 0)
    short_pnl = stats.get("pnl_short_7d", 0)
    if name.startswith("options") and stats.get("trades_7d", 0) >= MIN_7D_TRADES:
        if long_pnl < 0 and short_pnl > abs(long_pnl):
            new["side_bias"] = "short"
            reasons.append(f"options long P&L ${long_pnl:.0f}, short ${short_pnl:.0f} -> bias=short (PUT-only)")
        elif short_pnl < 0 and long_pnl > abs(short_pnl):
            new["side_bias"] = "long"
            reasons.append(f"options short P&L ${short_pnl:.0f}, long ${long_pnl:.0f} -> bias=long (CALL-only)")

    if abs(new["size_multiplier"] - old_mult) > 0.001 or reasons:
        new["rationale"] = " | ".join(reasons) if reasons else "no change"
    else:
        new["rationale"] = "no change (within thresholds)"

    return new


# ─── Top-level orchestration ─────────────────────────────────────────────────

def adapt(state: dict, today_stats: dict) -> tuple[dict, list[str]]:
    """
    Top-level adapter.

    Inputs:
      state:        current learning-loop/state.json contents (or {} if first run)
      today_stats:  computed by analyzer.py — must include
                    {
                      "as_of": iso date,
                      "equity": float,
                      "starting_equity": float,
                      "by_strategy": {name: stats_dict, ...},
                      "by_asset_class": {...},
                      "by_source": {...},
                    }

    Returns:
      (new_state, rationale_lines) where rationale_lines is a list of
      one-liners describing each change made.
    """
    rationale: list[str] = []
    new_state = deepcopy(state) if state else {
        "version": "1.0",
        "days_tracked": 0,
        "cumulative": {"total_trades": 0, "total_pnl_usd": 0.0, "starting_equity": None},
        "strategies": {},
        "asset_classes": {},
        "sources": {},
        "next_actions": [],
        "global_overrides": {
            "options_side_bias": None,
            "max_open_options": None,
            "max_concurrent_per_strategy": {},
        },
    }

    today_iso = today_stats.get("as_of") or datetime.now(timezone.utc).date().isoformat()
    new_state["last_updated"] = datetime.now(timezone.utc).isoformat()
    new_state["days_tracked"] = (state.get("days_tracked", 0) if state else 0) + 1
    new_state["cumulative"]   = {
        "total_trades":     today_stats.get("cumulative_trades",   0),
        "total_pnl_usd":    today_stats.get("cumulative_pnl_usd",  0.0),
        "starting_equity":  today_stats.get("starting_equity") or
                             (state.get("cumulative", {}).get("starting_equity") if state else None),
    }

    # Per-strategy adapt
    next_actions: list[str] = []
    for strat_name, strat_stats in today_stats.get("by_strategy", {}).items():
        old = (state.get("strategies", {}) if state else {}).get(strat_name, {})
        new = adapt_strategy(strat_name, old, strat_stats, today_stats.get("equity", 0))

        # Detect changes vs old for rationale + next_actions
        old_mult = old.get("size_multiplier", 1.0)
        new_mult = new["size_multiplier"]
        if abs(new_mult - old_mult) > 0.001:
            line = f"{strat_name}: size_multiplier {old_mult:.2f} -> {new_mult:.2f}"
            rationale.append(f"{today_iso} · {line} · {new['rationale']}")
            next_actions.append(line)
        if old.get("enabled", True) != new.get("enabled", True):
            line = f"{strat_name}: enabled {old.get('enabled', True)} -> {new['enabled']}"
            rationale.append(f"{today_iso} · {line} · {new['rationale']}")
            next_actions.append(line)
        if old.get("side_bias") != new.get("side_bias"):
            line = f"{strat_name}: side_bias {old.get('side_bias')} -> {new['side_bias']}"
            rationale.append(f"{today_iso} · {line} · {new['rationale']}")
            next_actions.append(line)

        new_state["strategies"][strat_name] = new

    new_state["asset_classes"] = today_stats.get("by_asset_class", {})
    new_state["sources"]       = today_stats.get("by_source", {})
    new_state["next_actions"]  = next_actions

    if not rationale:
        rationale.append(f"{today_iso} · no parameter changes (all strategies within thresholds)")

    return new_state, rationale


# ─── Lane2 auto-added — Detect options-momentum fill rate below 50% over 5+ orders and alert to widen limits ────────────

def heuristic_options_limit_too_tight(fill_stats: dict) -> tuple:
    """Flag when options-momentum limits are systematically too tight."""
    opts = fill_stats.get("options-momentum", {})
    placed = opts.get("placed", 0)
    fill_rate = opts.get("fill_rate", 1.0)
    if placed >= 5 and fill_rate < 0.5:
        return True, (
            f"options-momentum fill_rate {fill_rate:.0%} over {placed} orders"
            " — limits too tight, widen to ask+1% or mid+3%"
        )
    return False, ""
