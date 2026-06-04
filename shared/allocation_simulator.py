"""v3.19.0 (2026-06-04) — Allocation Simulator.

WHY
---
Closes audit-board READINESS-related question: "if I'd allocated capital
differently across enabled strategies based on observed paper performance,
what would the paper portfolio look like?"

This module simulates 6 allocation modes over the existing paper-trade
ledger. It is **paper analysis only** — it cannot raise risk limits, cannot
increase position sizes, cannot auto-allocate real capital. The output is a
diagnostic report the operator reads to inform manual judgments.

CONTRACT
--------
- simulate_allocation(mode, ...) is a PURE function: reads only the metrics
  dict passed in. No broker calls. No state.json or runtime_state.json
  writes.
- compare_allocation_modes(metrics, ...) runs all 6 modes and returns the
  comparison table.
- generate_allocation_report(...) reads the paper ledger via
  shared.paper_experiment and renders docs/allocation_simulation_LATEST.md
  + .json.

MODES
-----
- equal_weight          — each enabled strategy gets 1/N of capital.
- confidence_weighted   — weighted by paper profit factor.
- risk_adjusted         — PF / max_drawdown (penalises high-DD strategies).
- drawdown_capped       — equal weight, but skip strategies with PF<1 or
                          max_dd > drawdown_cap_pct.
- regime_aware          — boost strategies whose per_regime performance
                          favours the current regime.
- top_n                 — equal weight across top-N by composite score.

SAFETY GUARANTEES
-----------------
- NEVER changes runtime risk limits.
- NEVER raises position sizes.
- NEVER calls broker / network.
- NEVER auto-allocates real capital.
- Conservative: missing inputs → mode skipped with a note (not crash).
- Capital is a HYPOTHETICAL accounting unit; default $100k mirrors paper.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ALLOCATION_MODES = (
    "equal_weight",
    "confidence_weighted",
    "risk_adjusted",
    "drawdown_capped",
    "regime_aware",
    "top_n",
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:
            return default
        return v
    except (TypeError, ValueError):
        return default


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _is_eligible(metrics: dict) -> bool:
    """A strategy needs at least one closed trade to participate."""
    return _safe_int(metrics.get("n_closed", 0)) >= 1


def _filter_disabled(per_strategy: dict, disabled: list[str] | None) -> dict:
    if not disabled:
        return per_strategy
    s = set(disabled)
    return {k: v for k, v in per_strategy.items() if k not in s}


# ─── Composite score per strategy (used by top_n + confidence_weighted) ──────

def _composite_strategy_score(m: dict) -> float:
    """Cap-bounded score combining PF, expectancy, and sample size."""
    n = _safe_int(m.get("n_closed", 0))
    if n <= 0:
        return 0.0
    pf = _safe_float(m.get("profit_factor", 0.0))
    expectancy = _safe_float(m.get("expectancy", 0.0))
    max_dd = _safe_float(m.get("max_drawdown", 0.0))

    # PF component (1.0 = neutral, 2.0 → strong, cap at 3.0)
    pf_norm = min(max(pf, 0.0), 3.0) / 3.0
    # Expectancy sign + magnitude
    exp_norm = 0.5 + 0.5 * math.tanh(expectancy)
    # Drawdown penalty (lower DD = higher score)
    dd_norm = 1.0 - min(max(max_dd, 0.0), 1.0)
    # Sample-size confidence (n=10 → 0.5, n=50 → 1.0)
    sample_norm = min(1.0, n / 50.0)
    raw = 0.40 * pf_norm + 0.20 * exp_norm + 0.20 * dd_norm + 0.20 * sample_norm
    return max(0.0, min(1.0, raw))


# ─── Mode implementations ────────────────────────────────────────────────────

def _mode_equal_weight(per_strategy: dict) -> dict[str, float]:
    eligible = [s for s, m in per_strategy.items() if _is_eligible(m)]
    n = len(eligible)
    if n == 0:
        return {}
    w = 1.0 / n
    return {s: w for s in eligible}


def _mode_confidence_weighted(per_strategy: dict) -> dict[str, float]:
    eligible = {s: m for s, m in per_strategy.items() if _is_eligible(m)}
    if not eligible:
        return {}
    # Use max(PF, 0.1) so a strategy with PF<1 still gets a tiny weight
    raws = {s: max(_safe_float(m.get("profit_factor"), 0.0), 0.1)
            for s, m in eligible.items()}
    total = sum(raws.values())
    if total <= 0:
        return _mode_equal_weight(per_strategy)
    return {s: v / total for s, v in raws.items()}


def _mode_risk_adjusted(per_strategy: dict) -> dict[str, float]:
    eligible = {s: m for s, m in per_strategy.items() if _is_eligible(m)}
    if not eligible:
        return {}
    # PF / max(max_dd, 0.05) — caps DD floor so PF doesn't blow up.
    raws: dict[str, float] = {}
    for s, m in eligible.items():
        pf = max(_safe_float(m.get("profit_factor"), 0.0), 0.0)
        dd = max(_safe_float(m.get("max_drawdown"), 0.05), 0.05)
        raws[s] = pf / dd
    total = sum(raws.values())
    if total <= 0:
        return _mode_equal_weight(per_strategy)
    return {s: v / total for s, v in raws.items()}


def _mode_drawdown_capped(per_strategy: dict,
                           drawdown_cap_pct: float) -> dict[str, float]:
    eligible = {}
    for s, m in per_strategy.items():
        if not _is_eligible(m):
            continue
        pf = _safe_float(m.get("profit_factor"), 0.0)
        dd = _safe_float(m.get("max_drawdown"), 0.0)
        if pf >= 1.0 and dd <= drawdown_cap_pct:
            eligible[s] = m
    if not eligible:
        return {}
    w = 1.0 / len(eligible)
    return {s: w for s in eligible}


def _mode_regime_aware(per_strategy: dict, current_regime: str) -> dict[str, float]:
    if not current_regime:
        return _mode_equal_weight(per_strategy)
    eligible = {s: m for s, m in per_strategy.items() if _is_eligible(m)}
    if not eligible:
        return {}
    raws: dict[str, float] = {}
    for s, m in eligible.items():
        per_regime = m.get("per_regime") or {}
        if not isinstance(per_regime, dict):
            raws[s] = 0.5
            continue
        regime_stats = per_regime.get(current_regime)
        if not isinstance(regime_stats, dict):
            raws[s] = 0.5
            continue
        pf = _safe_float(regime_stats.get("profit_factor"), 0.0)
        n = _safe_int(regime_stats.get("n_closed"), 0)
        # Blend with base PF based on regime sample size.
        base_pf = _safe_float(m.get("profit_factor"), 0.0)
        if n >= 5:
            blended = pf  # trust regime stats
        elif n > 0:
            blended = (pf + base_pf) / 2.0
        else:
            blended = base_pf
        raws[s] = max(blended, 0.1)
    total = sum(raws.values())
    if total <= 0:
        return _mode_equal_weight(per_strategy)
    return {s: v / total for s, v in raws.items()}


def _mode_top_n(per_strategy: dict, n: int) -> dict[str, float]:
    eligible = {s: m for s, m in per_strategy.items() if _is_eligible(m)}
    if not eligible:
        return {}
    scored = sorted(eligible.items(),
                     key=lambda kv: -_composite_strategy_score(kv[1]))
    top = scored[: max(1, n)]
    if not top:
        return {}
    w = 1.0 / len(top)
    return {s: w for s, _m in top}


# ─── Per-strategy exposure aggregation ───────────────────────────────────────

def _aggregate_exposure(weights: dict[str, float],
                         per_strategy: dict) -> dict:
    """Aggregate exposure by strategy / symbol / regime."""
    by_strategy: dict[str, float] = {}
    by_symbol: dict[str, float] = {}
    by_regime: dict[str, float] = {}
    for s, w in weights.items():
        by_strategy[s] = w
        m = per_strategy.get(s) or {}
        # Symbol exposure ∝ |net_pnl| share within per_symbol.
        per_sym = m.get("per_symbol") or {}
        if isinstance(per_sym, dict) and per_sym:
            tot = sum(abs(_safe_float((sm or {}).get("net_pnl_after_fees_slippage", 0.0)))
                      for sm in per_sym.values())
            if tot > 0:
                for sym, sm in per_sym.items():
                    if not isinstance(sm, dict):
                        continue
                    share = abs(_safe_float(sm.get("net_pnl_after_fees_slippage", 0.0))) / tot
                    by_symbol[sym] = by_symbol.get(sym, 0.0) + w * share
        # Regime exposure
        per_reg = m.get("per_regime") or {}
        if isinstance(per_reg, dict) and per_reg:
            tot = sum(_safe_int((rm or {}).get("n_closed", 0))
                      for rm in per_reg.values())
            if tot > 0:
                for reg, rm in per_reg.items():
                    if not isinstance(rm, dict):
                        continue
                    share = _safe_int(rm.get("n_closed", 0)) / tot
                    by_regime[reg] = by_regime.get(reg, 0.0) + w * share

    def _round_dict(d: dict) -> dict:
        return {k: round(float(v), 6) for k, v in d.items()}

    return {
        "exposure_by_strategy": _round_dict(by_strategy),
        "exposure_by_symbol":   _round_dict(by_symbol),
        "exposure_by_regime":   _round_dict(by_regime),
    }


# ─── Portfolio metrics from weights ──────────────────────────────────────────

def _compute_portfolio_metrics(weights: dict[str, float],
                                per_strategy: dict,
                                capital_usd: float) -> dict:
    """Compute paper-portfolio aggregate metrics given weight allocations.

    Pure accounting — applies weight to per-strategy net_pnl as a scaling
    proxy. This is a HYPOTHETICAL paper analysis, not a re-simulation.
    """
    total_pnl = 0.0
    total_gross = 0.0
    total_costs = 0.0
    worst_day = 0.0
    worst_streak = 0
    weighted_dd = 0.0
    weighted_vol = 0.0
    grosses_total = 0.0
    losses_total = 0.0

    for s, w in weights.items():
        m = per_strategy.get(s) or {}
        net = _safe_float(m.get("net_pnl_after_fees_slippage"), 0.0)
        gross = _safe_float(m.get("gross_pnl"), 0.0)
        cost = _safe_float(m.get("total_costs"), 0.0)
        # PF reconstruction: gross_wins / gross_losses
        # We approximate gross_wins / gross_losses contributions:
        pf = _safe_float(m.get("profit_factor"), 0.0)
        if gross > 0 and pf > 0:
            gross_wins = gross + cost * 0  # approx ignoring sign
        else:
            gross_wins = 0.0

        total_pnl   += w * net
        total_gross += w * gross
        total_costs += w * cost
        # Aggregate gross wins/losses for PF reconstruction
        if pf > 0:
            # gross_wins == pf * gross_losses; total = gross_wins + gross_losses
            if pf == 999.0 or pf > 100.0:
                grosses_total += w * abs(gross)
            else:
                # Approximate gross_wins / gross_losses split
                total_abs = abs(gross) + cost
                # share_win = pf/(pf+1)
                share_win = pf / (pf + 1.0)
                grosses_total += w * total_abs * share_win
                losses_total  += w * total_abs * (1.0 - share_win)

        # DD weighted
        dd = _safe_float(m.get("max_drawdown"), 0.0)
        weighted_dd += w * dd
        # Volatility proxy: avg_win - avg_loss magnitude
        avg_win = _safe_float(m.get("avg_win"), 0.0)
        avg_loss = abs(_safe_float(m.get("avg_loss"), 0.0))
        weighted_vol += w * (avg_win + avg_loss) / 2.0
        # Worst losing streak (max across)
        streak = _safe_int(m.get("longest_losing_streak"), 0)
        if streak > worst_streak:
            worst_streak = streak
        # Worst day proxy (avg_loss * w as conservative single-day proxy)
        worst_day = min(worst_day, -avg_loss * w)

    # Profit factor of portfolio (approx)
    if losses_total > 0:
        portfolio_pf = grosses_total / losses_total
    elif grosses_total > 0:
        portfolio_pf = 999.0
    else:
        portfolio_pf = 0.0

    # Expectancy ≈ total_pnl / total_trades equivalent
    total_n = sum(_safe_int((per_strategy.get(s) or {}).get("n_closed"), 0)
                  for s in weights)
    expectancy = (total_pnl / total_n) if total_n > 0 else 0.0

    return {
        "total_paper_pnl_usd":      round(float(total_pnl), 4),
        "max_paper_drawdown_pct":   round(float(weighted_dd), 6),
        "volatility_proxy":         round(float(weighted_vol), 6),
        "profit_factor":            round(float(portfolio_pf), 4),
        "expectancy":               round(float(expectancy), 6),
        "worst_day_pnl":            round(float(worst_day), 4),
        "worst_streak_losses":      int(worst_streak),
    }


def _correlation_proxy(weights: dict[str, float],
                        per_strategy: dict) -> float | None:
    """A rough correlation proxy: share of weight in same regime/symbol.

    Returns None if we don't have enough data. Higher = more concentrated.
    """
    if not weights:
        return None
    agg = _aggregate_exposure(weights, per_strategy)
    by_sym = agg.get("exposure_by_symbol") or {}
    if not by_sym:
        return None
    max_sym = max(by_sym.values())
    return round(float(max_sym), 6)


# ─── Public API ──────────────────────────────────────────────────────────────

def simulate_allocation(mode: str,
                         *,
                         per_strategy_paper_metrics: dict,
                         current_regime: str = "NEUTRAL",
                         capital_usd: float = 100_000.0,
                         top_n: int = 5,
                         drawdown_cap_pct: float = 0.20,
                         disabled_strategies: list[str] | None = None,
                         ) -> dict:
    """Simulate paper portfolio with given allocation mode.

    PURE FUNCTION. Reads only the per-strategy metrics dict.
    NEVER changes runtime risk limits. NEVER auto-allocates capital.
    Conservative: missing data → mode skipped with a note.

    Returns a dict; see module docstring for shape.
    """
    if not isinstance(per_strategy_paper_metrics, dict):
        return _empty_result(mode, note="per_strategy_paper_metrics_not_dict")

    if mode not in ALLOCATION_MODES:
        return _empty_result(mode, note=f"unknown_mode:{mode}")

    per_strategy = _filter_disabled(per_strategy_paper_metrics,
                                     disabled_strategies)
    if not per_strategy:
        return _empty_result(mode, note="no_strategies_after_filter")

    try:
        if mode == "equal_weight":
            weights = _mode_equal_weight(per_strategy)
        elif mode == "confidence_weighted":
            weights = _mode_confidence_weighted(per_strategy)
        elif mode == "risk_adjusted":
            weights = _mode_risk_adjusted(per_strategy)
        elif mode == "drawdown_capped":
            weights = _mode_drawdown_capped(per_strategy, drawdown_cap_pct)
        elif mode == "regime_aware":
            weights = _mode_regime_aware(per_strategy, current_regime)
        elif mode == "top_n":
            weights = _mode_top_n(per_strategy, top_n)
        else:
            return _empty_result(mode, note="mode_not_implemented")
    except Exception as e:  # pragma: no cover — fail-soft
        return _empty_result(mode, note=f"mode_error:{type(e).__name__}:{e}")

    if not weights:
        return _empty_result(mode, note="no_eligible_strategies",
                              capital_usd=capital_usd,
                              current_regime=current_regime)

    portfolio = _compute_portfolio_metrics(weights, per_strategy, capital_usd)
    expo = _aggregate_exposure(weights, per_strategy)
    corr = _correlation_proxy(weights, per_strategy)

    return {
        "mode":                     mode,
        "capital_usd":              round(float(capital_usd), 2),
        "current_regime":           str(current_regime or "NEUTRAL"),
        "weights":                  {k: round(float(v), 6) for k, v in weights.items()},
        "exposure_by_strategy":     expo["exposure_by_strategy"],
        "exposure_by_symbol":       expo["exposure_by_symbol"],
        "exposure_by_regime":       expo["exposure_by_regime"],
        "total_paper_pnl_usd":      portfolio["total_paper_pnl_usd"],
        "max_paper_drawdown_pct":   portfolio["max_paper_drawdown_pct"],
        "volatility_proxy":         portfolio["volatility_proxy"],
        "profit_factor":            portfolio["profit_factor"],
        "expectancy":               portfolio["expectancy"],
        "worst_day_pnl":            portfolio["worst_day_pnl"],
        "worst_streak_losses":      portfolio["worst_streak_losses"],
        "correlation_proxy":        corr,
        "notes":                    "paper_analysis_only",
    }


def _empty_result(mode: str, *, note: str,
                   capital_usd: float = 0.0,
                   current_regime: str = "NEUTRAL") -> dict:
    return {
        "mode":                     mode,
        "capital_usd":              round(float(capital_usd), 2),
        "current_regime":           current_regime,
        "weights":                  {},
        "exposure_by_strategy":     {},
        "exposure_by_symbol":       {},
        "exposure_by_regime":       {},
        "total_paper_pnl_usd":      0.0,
        "max_paper_drawdown_pct":   0.0,
        "volatility_proxy":         0.0,
        "profit_factor":            0.0,
        "expectancy":               0.0,
        "worst_day_pnl":            0.0,
        "worst_streak_losses":      0,
        "correlation_proxy":        None,
        "notes":                    f"paper_analysis_only:{note}",
    }


def compare_allocation_modes(per_strategy_paper_metrics: dict,
                              **kwargs) -> dict:
    """Run all 6 modes + return comparison table.

    Returns:
      {
        "modes_compared": list[str],
        "results":        {mode → simulate_allocation result},
        "best_by_pnl":    mode_name or None,
        "best_by_pf":     mode_name or None,
        "best_by_dd":     mode_name or None,   # lowest DD
        "notes":          str,
      }
    """
    results: dict[str, dict] = {}
    for mode in ALLOCATION_MODES:
        try:
            results[mode] = simulate_allocation(
                mode,
                per_strategy_paper_metrics=per_strategy_paper_metrics,
                **kwargs,
            )
        except Exception as e:  # pragma: no cover
            results[mode] = _empty_result(mode,
                                           note=f"compare_error:{type(e).__name__}")

    # Determine "best" — operator can read but no risk decisions follow.
    def _eligible(r: dict) -> bool:
        return r and r.get("weights")
    eligible = {m: r for m, r in results.items() if _eligible(r)}
    best_pnl = max(eligible.items(),
                   key=lambda kv: kv[1].get("total_paper_pnl_usd") or 0.0,
                   default=(None, None))[0] if eligible else None
    best_pf = max(eligible.items(),
                  key=lambda kv: kv[1].get("profit_factor") or 0.0,
                  default=(None, None))[0] if eligible else None
    best_dd = min(eligible.items(),
                  key=lambda kv: kv[1].get("max_paper_drawdown_pct") or 1.0,
                  default=(None, None))[0] if eligible else None

    return {
        "modes_compared": list(ALLOCATION_MODES),
        "results":        results,
        "best_by_pnl":    best_pnl,
        "best_by_pf":     best_pf,
        "best_by_dd":     best_dd,
        "notes":          "paper_analysis_only_no_risk_changes",
    }


# ─── Report generation ──────────────────────────────────────────────────────

def _read_paper_metrics_from_ledger(window_days: int = 180) -> dict:
    """Read per-strategy metrics from shared/paper_experiment ledger."""
    try:
        try:
            from paper_experiment import compute_strategy_metrics
        except ImportError:
            from shared.paper_experiment import compute_strategy_metrics  # type: ignore
        try:
            from backtest.strategy_registry import REGISTRY  # type: ignore
            names = sorted(REGISTRY.keys())
        except Exception:
            names = []
        out: dict[str, dict] = {}
        for name in names:
            try:
                m = compute_strategy_metrics(name, window_days=window_days)
                out[name] = m
            except Exception:
                continue
        return out
    except Exception:
        return {}


def _emit_evidence_audit(comparison: dict) -> None:
    """Emit a single audit event summarising the allocation analysis."""
    try:
        try:
            from audit import write_audit_event
        except ImportError:
            from shared.audit import write_audit_event  # type: ignore
        rec = {
            "type":          "allocation_simulation",
            "source":        "evidence_analysis",
            "decision":      "ANALYSED",
            "modes":         comparison.get("modes_compared") or [],
            "best_by_pnl":   comparison.get("best_by_pnl"),
            "best_by_pf":    comparison.get("best_by_pf"),
            "best_by_dd":    comparison.get("best_by_dd"),
            "decided_at":    datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"),
        }
        try:
            write_audit_event(rec, kind="trading")
        except Exception:
            pass
    except Exception:
        pass


def _format_markdown(comparison: dict, *, capital_usd: float,
                      current_regime: str) -> str:
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines: list[str] = []
    lines.append("# Allocation Simulation Report")
    lines.append("")
    lines.append(
        "*Paper analysis only. This simulation is informational. It "
        "DOES NOT auto-allocate capital and DOES NOT change runtime "
        "risk limits. Risk engine retains final say.*"
    )
    lines.append("")
    lines.append(
        f"Generated {now_iso} · capital_usd=`{capital_usd:.0f}` · "
        f"current_regime=`{current_regime}`")
    lines.append("")
    lines.append("| Mode | NetPnL | PF | MaxDD | Vol | Expectancy | WorstStreak | Notes |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---|")
    results = comparison.get("results") or {}
    for mode in comparison.get("modes_compared") or ALLOCATION_MODES:
        r = results.get(mode) or {}
        lines.append(
            f"| {mode} | "
            f"{_safe_float(r.get('total_paper_pnl_usd')):+.2f} | "
            f"{_safe_float(r.get('profit_factor')):.2f} | "
            f"{_safe_float(r.get('max_paper_drawdown_pct'))*100:.1f}% | "
            f"{_safe_float(r.get('volatility_proxy')):.3f} | "
            f"{_safe_float(r.get('expectancy')):+.4f} | "
            f"{_safe_int(r.get('worst_streak_losses'))} | "
            f"{r.get('notes') or ''} |"
        )
    lines.append("")
    lines.append("## Best mode by metric")
    lines.append("")
    lines.append(f"- Best by NetPnL: `{comparison.get('best_by_pnl') or 'n/a'}`")
    lines.append(f"- Best by PF:     `{comparison.get('best_by_pf') or 'n/a'}`")
    lines.append(f"- Best by MaxDD:  `{comparison.get('best_by_dd') or 'n/a'}` (lowest)")
    lines.append("")
    lines.append(
        "> Reminder: best-by-x ≠ live recommendation. The operator reads "
        "this report; the system never auto-allocates real capital from it.")
    return "\n".join(lines) + "\n"


def generate_allocation_report(
    *,
    out_md_path: str | None = None,
    out_json_path: str | None = None,
    capital_usd: float = 100_000.0,
    current_regime: str = "NEUTRAL",
    top_n: int = 5,
    drawdown_cap_pct: float = 0.20,
    disabled_strategies: list[str] | None = None,
    window_days: int = 180,
    per_strategy_paper_metrics: dict | None = None,
) -> tuple[str, str]:
    """Read paper ledger + compute all modes + write reports.

    Returns (md_path, json_path). Empty string if a path was skipped.
    """
    import json as _json

    if per_strategy_paper_metrics is None:
        per_strategy_paper_metrics = _read_paper_metrics_from_ledger(
            window_days=window_days)

    comparison = compare_allocation_modes(
        per_strategy_paper_metrics,
        current_regime=current_regime,
        capital_usd=capital_usd,
        top_n=top_n,
        drawdown_cap_pct=drawdown_cap_pct,
        disabled_strategies=disabled_strategies,
    )

    _emit_evidence_audit(comparison)

    repo_root = Path(__file__).resolve().parent.parent
    md_target = out_md_path or str(
        repo_root / "docs" / "allocation_simulation_LATEST.md")
    json_target = out_json_path or str(
        repo_root / "docs" / "allocation_simulation_LATEST.json")

    md_written = ""
    json_written = ""
    md_body = _format_markdown(comparison,
                                capital_usd=capital_usd,
                                current_regime=current_regime)
    try:
        p = Path(md_target)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(md_body, encoding="utf-8")
        md_written = str(p)
    except Exception:
        pass

    payload = {
        "generated_at":  datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "capital_usd":   capital_usd,
        "current_regime": current_regime,
        "window_days":   window_days,
        "comparison":    comparison,
    }
    try:
        p = Path(json_target)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_json.dumps(payload, indent=2, sort_keys=True,
                                  default=str), encoding="utf-8")
        json_written = str(p)
    except Exception:
        pass

    return md_written, json_written


__all__ = [
    "ALLOCATION_MODES",
    "simulate_allocation",
    "compare_allocation_modes",
    "generate_allocation_report",
]
