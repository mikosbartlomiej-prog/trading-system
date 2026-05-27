"""learning-loop/edge_validator.py — gate strategy `enabled=true` on demonstrated edge.

v3.11 (2026-05-27): no strategy is allowed `enabled=true` in state.json
without a recent backtest pass meeting minimum thresholds.

THRESHOLDS (realistic mode, walk-forward):
  win_rate ≥ 50%
  profit_factor ≥ 1.3
  max_drawdown < 20%

This eliminates the "overbought-short" pattern (shipped enabled by default
based on conceptual fit; in production lost -$2,065 over 9 trades at
11% WR before being manually disabled). Going forward: NO strategy may
fire without observed edge in realistic backtest.

DATA SOURCE: backtest/results/<strategy>-*.json (latest by mtime).
Format expected (matches backtest/run.py output v3.10):
  {
    "strategy": "...",
    "mode": "both" | "realistic" | "idealized",
    "all_trades_realistic": [...],
    ...
  }

POLICY:
  If no backtest result exists for strategy: edge = UNKNOWN → block enable.
  If result exists but stale (>30 days): edge = STALE → block enable.
  If result < thresholds: edge = FAIL → block enable.
  If result ≥ thresholds: edge = PASS → allow enable.

OVERRIDE: env `EDGE_GATE_DISABLED=true` skips the gate entirely (operator
opt-out for emergencies / new strategy bootstrap).

Allocator-level tags (`alloc-exit`, `allocator-rebalance`, etc.) are NEVER
gated — they're operational tags, not signal strategies.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional


# Thresholds — conservative; tunable via env if needed
MIN_WIN_RATE = float(os.environ.get("EDGE_MIN_WIN_RATE", "0.50"))
MIN_PROFIT_FACTOR = float(os.environ.get("EDGE_MIN_PROFIT_FACTOR", "1.3"))
MAX_DRAWDOWN_PCT = float(os.environ.get("EDGE_MAX_DRAWDOWN_PCT", "0.20"))
MIN_TRADES = int(os.environ.get("EDGE_MIN_TRADES", "10"))
MAX_BACKTEST_AGE_DAYS = int(os.environ.get("EDGE_MAX_BACKTEST_AGE_DAYS", "30"))

# Allocator-level tags exempt from edge gate (operational, not signal)
ALLOCATOR_LEVEL_TAGS = {
    "alloc-exit", "alloc-reduce", "allocator-rebalance",
    "op-correction", "operational-correction",
    "emergency-close", "unknown",
}


_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKTEST_RESULTS = _REPO_ROOT / "backtest" / "results"


def _is_disabled() -> bool:
    """v3.11 first ship: default DISABLED (true). Operator opts IN by
    setting EDGE_GATE_DISABLED=false AFTER running backtests for all
    currently-enabled strategies. Same pattern as Layer 1 incident-detector
    auto-disable (default off).

    Migration plan to enforced:
      1. Operator runs `python3 -m backtest.run --strategy <each> --tickers <list> --days 180`
         for each strategy in state.json. Results land in backtest/results/.
      2. Inspect edge_validator output via `python3 -c \"...\"` per-strategy.
      3. When 100% of currently-enabled strategies have PASS results,
         set EDGE_GATE_DISABLED=false in daily-learning.yml env.
      4. Adapter then enforces; any strategy losing edge gets auto-disabled.
    """
    return os.environ.get("EDGE_GATE_DISABLED", "true").lower() == "true"


def _find_latest_backtest(strategy_name: str) -> Optional[Path]:
    """Return path to most recent backtest result for strategy, or None."""
    if not _BACKTEST_RESULTS.exists():
        return None
    candidates = list(_BACKTEST_RESULTS.glob(f"{strategy_name}-*.json"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _compute_metrics(trades: list) -> dict:
    """Compute WR + PF + MDD from trades list."""
    if not trades:
        return {"n_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
                "max_drawdown_pct": 0.0}

    n = len(trades)
    wins = [t for t in trades if t.get("pnl_usd", 0) > 0]
    losses = [t for t in trades if t.get("pnl_usd", 0) < 0]
    n_wins = len(wins)

    total_win = sum(t.get("pnl_usd", 0) for t in wins)
    total_loss = abs(sum(t.get("pnl_usd", 0) for t in losses))

    win_rate = n_wins / n if n > 0 else 0.0
    profit_factor = (total_win / total_loss) if total_loss > 0 else (
        float("inf") if total_win > 0 else 0.0
    )

    # Max drawdown — cumulative equity curve
    cum_pnl = 0.0
    peak = 0.0
    max_dd_pct = 0.0
    for t in trades:
        cum_pnl += t.get("pnl_usd", 0)
        if cum_pnl > peak:
            peak = cum_pnl
        if peak > 0:
            dd_pct = (peak - cum_pnl) / peak
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

    return {
        "n_trades": n,
        "win_rate": win_rate,
        "profit_factor": profit_factor if profit_factor != float("inf") else 999.0,
        "max_drawdown_pct": max_dd_pct,
    }


def validate_strategy_edge(strategy_name: str) -> tuple[bool, dict, str]:
    """
    Returns (ok, metrics, reason).

    ok = True only if all thresholds met.
    Tags ALLOCATOR_LEVEL_TAGS always return (True, {}, "operational-tag exempt").
    """
    # Operational tags always pass
    if strategy_name in ALLOCATOR_LEVEL_TAGS:
        return (True, {}, f"{strategy_name}: operational tag (exempt from edge gate)")

    if _is_disabled():
        return (True, {}, "EDGE_GATE_DISABLED=true (operator override)")

    bt_path = _find_latest_backtest(strategy_name)
    if not bt_path:
        return (False, {}, f"{strategy_name}: no backtest result found in backtest/results/")

    # Staleness check
    age_days = (datetime.now(timezone.utc).timestamp() - bt_path.stat().st_mtime) / 86400
    if age_days > MAX_BACKTEST_AGE_DAYS:
        return (False, {"age_days": round(age_days, 1)},
                f"{strategy_name}: backtest stale ({age_days:.1f}d > {MAX_BACKTEST_AGE_DAYS}d)")

    try:
        data = json.loads(bt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return (False, {}, f"{strategy_name}: backtest result parse error ({e})")

    # Prefer realistic trades; fallback to all_trades if old format
    trades = (data.get("all_trades_realistic")
              or data.get("all_trades")
              or [])
    metrics = _compute_metrics(trades)
    metrics["age_days"] = round(age_days, 1)
    metrics["source"] = bt_path.name

    if metrics["n_trades"] < MIN_TRADES:
        return (False, metrics,
                f"{strategy_name}: insufficient sample n={metrics['n_trades']} < {MIN_TRADES}")

    if metrics["win_rate"] < MIN_WIN_RATE:
        return (False, metrics,
                f"{strategy_name}: WR={metrics['win_rate']:.2%} < {MIN_WIN_RATE:.0%} threshold")

    if metrics["profit_factor"] < MIN_PROFIT_FACTOR:
        return (False, metrics,
                f"{strategy_name}: PF={metrics['profit_factor']:.2f} < {MIN_PROFIT_FACTOR}")

    if metrics["max_drawdown_pct"] >= MAX_DRAWDOWN_PCT:
        return (False, metrics,
                f"{strategy_name}: MDD={metrics['max_drawdown_pct']:.1%} >= {MAX_DRAWDOWN_PCT:.0%}")

    return (True, metrics,
            f"{strategy_name}: edge VERIFIED — WR={metrics['win_rate']:.0%} "
            f"PF={metrics['profit_factor']:.2f} MDD={metrics['max_drawdown_pct']:.1%} "
            f"n={metrics['n_trades']} (backtest {metrics['source']}, age={metrics['age_days']}d)")


def enforce_regime_gate(state: dict, current_regime: str) -> tuple[dict, list[str]]:
    """v3.11 Phase E (2026-05-27): block strategy if current regime not in
    strategy's compatible_regimes list.

    state['strategies'][name].compatible_regimes = ["RISK_ON", "NEUTRAL", ...]
    If field missing → all regimes allowed (backward compat).
    If field present and current_regime NOT in list → enabled=False with
    `paused_by_regime=true` flag (auto-resumes when regime changes back).
    """
    log = []
    if not current_regime:
        return state, log

    strats = state.get("strategies", {})
    for name, cfg in strats.items():
        if not isinstance(cfg, dict):
            continue
        if name in ALLOCATOR_LEVEL_TAGS:
            continue
        compat = cfg.get("compatible_regimes")
        if not compat:
            continue  # no constraint
        if current_regime not in compat:
            if cfg.get("enabled"):
                cfg["enabled"] = False
                cfg["paused_by_regime"] = True
                cfg["paused_regime_at"] = current_regime
                log.append(f"regime-gate: {name} paused — regime={current_regime} not in {compat}")
        else:
            # Auto-resume if previously paused-by-regime AND regime now compatible
            if cfg.get("paused_by_regime"):
                cfg["enabled"] = True
                cfg.pop("paused_by_regime", None)
                cfg.pop("paused_regime_at", None)
                log.append(f"regime-gate: {name} RESUMED — regime={current_regime} now compatible")
    return state, log


def enforce_edge_gate_on_state(state: dict) -> tuple[dict, list[str]]:
    """
    Walk state['strategies'][*] and force enabled=False where edge fails.
    Returns (state, change_log).

    Does NOT modify operational-tag strategies (alloc-*, etc.).
    Existing `enabled=false` stays false. Only `enabled=true` is gated.
    """
    if _is_disabled():
        return state, ["edge-gate: DISABLED via EDGE_GATE_DISABLED env"]

    log = []
    strats = state.get("strategies", {})

    for name, cfg in strats.items():
        if not isinstance(cfg, dict):
            continue
        if name in ALLOCATOR_LEVEL_TAGS:
            continue
        # Operator override per-strategy
        if cfg.get("edge_gate_override") is True:
            log.append(f"edge-gate: {name} edge_gate_override=true → skipped")
            continue
        if not cfg.get("enabled"):
            continue  # already disabled, leave alone

        ok, metrics, reason = validate_strategy_edge(name)
        if not ok:
            cfg["enabled"] = False
            cfg["paused_until"] = None
            cfg["hard_safety"] = True
            cfg["rationale"] = f"edge-gate FAIL: {reason}"
            cfg["edge_metrics"] = metrics
            log.append(f"edge-gate: {name} → enabled=False ({reason})")
        else:
            cfg["edge_metrics"] = metrics
            log.append(f"edge-gate: {name} PASS ({reason})")

    return state, log
