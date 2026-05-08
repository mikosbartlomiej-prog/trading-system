"""
Read-only access to learning-loop/state.json for monitors.

Monitors call `load_strategy_state(name)` at the start of their run to
get adapted parameters (size_multiplier, enabled, side_bias) produced
by the daily learning loop. State is committed to git by daily-learning
workflow so every cron picks up the latest version after checkout.

Fail-safe: missing or corrupted state.json -> returns empty dict ->
monitors fall back to defaults baked in their own constants.
"""

import json
import os

_STATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..', 'learning-loop', 'state.json',
)


def _read_state() -> dict:
    try:
        with open(_STATE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def load_strategy_state(strategy_name: str) -> dict:
    """
    Returns the per-strategy adapted parameters dict, or {} if no state
    exists yet (monitors fall back to their hardcoded defaults).

    Typical fields when present:
      size_multiplier: float in [0.30, 2.00]
      enabled:         bool
      side_bias:       "long" | "short" | None
      paused_until:    ISO date string when auto-resume happens
      rationale:       human-readable last-change reason
      stats fields:    trades_7d, win_rate_7d, pnl_usd_7d, etc.
    """
    return _read_state().get("strategies", {}).get(strategy_name, {})


def load_global_overrides() -> dict:
    """Returns the global_overrides dict from state.json (or empty)."""
    return _read_state().get("global_overrides", {})


def is_strategy_enabled(strategy_name: str) -> bool:
    """Convenience: returns True (default) when strategy is enabled or no state exists."""
    return load_strategy_state(strategy_name).get("enabled", True)


def size_multiplier(strategy_name: str) -> float:
    """Convenience: returns the adapted size multiplier (default 1.0)."""
    return float(load_strategy_state(strategy_name).get("size_multiplier", 1.0))


def side_bias(strategy_name: str) -> str | None:
    """Convenience: returns 'long' / 'short' / None."""
    return load_strategy_state(strategy_name).get("side_bias")


# ─── Per-ticker state (orthogonal to per-strategy) ───────────────────────────
#
# Some tickers should be paused regardless of which strategy is firing —
# e.g. when a backtest demonstrates the strategy is structurally trapped
# on that ticker (high-beta gap risk, broken momentum, etc.). This is
# orthogonal to per-strategy disable: a strategy stays on globally but
# skips specific symbols.

def load_ticker_state(ticker: str) -> dict:
    """
    Returns the per-ticker override dict from state.json:
      {
        "enabled":      bool,           # default True if missing
        "rationale":    "...",          # why disabled
        "paused_until": "YYYY-MM-DD" or None,  # null = manual re-enable only
        "evidence":     "...",          # backtest reference, etc.
      }
    or {} if no override exists.
    """
    return _read_state().get("tickers", {}).get(ticker, {})


def is_ticker_enabled(ticker: str) -> bool:
    """Convenience: True (default) when ticker is enabled or no override exists."""
    return load_ticker_state(ticker).get("enabled", True)


def disabled_tickers() -> list[str]:
    """List of tickers explicitly disabled via state.json. Used for banner-log."""
    return [
        t for t, info in (_read_state().get("tickers") or {}).items()
        if info and not info.get("enabled", True)
    ]
