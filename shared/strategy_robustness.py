"""v3.20.0 (2026-06-04) — ETAP 5 — Strategy Robustness & Ablation Sandbox.

Closes audit-board STRAT-003 robustness layer: a strategy that looks good
on a single set of parameters and a single set of trades is not yet
trustworthy. We need to know:

  * Is the result fragile to ±10% / ±20% changes in entry/exit knobs?
  * Does it survive realistic slippage / spread sensitivity?
  * Does it hold up across different time windows / regimes / symbols?
  * Is it dominated by a single outsized trade, day, or symbol?

This module answers those questions in a *sandbox* that runs offline,
never mutates the runtime, never talks to the broker, never uses a paid
API, and never auto-optimizes parameters.

DESIGN PRINCIPLES
-----------------
1. ``SANDBOX_NEVER_OPTIMIZES = True`` and ``SANDBOX_NEVER_MUTATES_RUNTIME
   = True`` are module-level sentinels that the test suite asserts.
2. All operations are deterministic. Same input → same output.
3. No external library beyond ``statistics`` from stdlib.
4. Fail-soft. Errors → empty result + ``error`` field; never raise.

PUBLIC API
----------
``run_robustness_suite(strategy, ledger, *, params=None, simulator=None)``
    Run the full suite. Returns a dict with ``robustness_score``,
    ``fragility_warnings``, ``parameter_sensitivity``,
    ``overfit_suspicion``, ``dependency_on_one_symbol``,
    ``dependency_on_one_day``, ``dependency_on_one_regime``, and the
    per-axis sub-results.

The optional ``simulator`` argument is a *pure* callable
``simulator(ledger, *, params, slippage_bps, spread_bps) -> list[dict]``
that returns a synthetic re-ledger under perturbed assumptions. Unit
tests pass a stub. Production callers either pass a deterministic
historical replayer or skip the sweeps (the sandbox still computes
data-splits + drop-one ablations without a simulator).

CONTRACT NOTE
-------------
``robustness_score = 1.0 - max_relative_degradation`` where degradation
is the worst observed drop in expectancy across any sweep variant,
relative to the baseline expectancy. Clamped to [0, 1].
"""

from __future__ import annotations

import statistics
from typing import Any, Callable, Sequence

# ─── Sandbox invariants (asserted in tests) ──────────────────────────────────

SANDBOX_NEVER_OPTIMIZES        = True
SANDBOX_NEVER_MUTATES_RUNTIME  = True

# ─── Sweep configuration ─────────────────────────────────────────────────────

PARAM_PERTURBATIONS: tuple[float, ...] = (-0.20, -0.10, 0.10, 0.20)
SLIPPAGE_BPS_SAMPLES: tuple[float, ...] = (0.0, 2.0, 5.0, 10.0)
SPREAD_BPS_SAMPLES: tuple[float, ...] = (0.0, 1.0, 3.0, 7.0)

# Thresholds for fragility warnings.
DEGRADATION_FRAGILITY_THRESHOLD = 0.30   # 30% drop in expectancy
SLIPPAGE_FRAGILITY_THRESHOLD    = 0.40
SPREAD_FRAGILITY_THRESHOLD      = 0.40
TIME_SPLIT_FRAGILITY_THRESHOLD  = 0.50
REGIME_SPLIT_FRAGILITY_THRESHOLD = 0.50
SYMBOL_SPLIT_FRAGILITY_THRESHOLD = 0.50

OVERFIT_SUSPICION_PCT           = 0.50   # one trade > 50% PnL
SINGLE_SYMBOL_DEPENDENCE_PCT    = 0.70   # one symbol > 70% PnL
SINGLE_DAY_DEPENDENCE_PCT       = 0.70
SINGLE_REGIME_DEPENDENCE_PCT    = 0.70

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:
            return default
        if v in (float("inf"), float("-inf")):
            return default
        return v
    except (TypeError, ValueError):
        return default


def _net(rec: dict) -> float:
    """Extract net P&L from a ledger record. Fall back through ``pnl_net``
    and ``pnl`` to stay tolerant of older record schemas.
    """
    for k in ("net_pnl", "pnl_net", "pnl"):
        if k in rec and rec[k] is not None:
            return _safe_float(rec[k])
    return 0.0


def _expectancy(ledger: Sequence[dict]) -> float:
    """Mean net P&L per trade. Returns 0.0 on empty."""
    if not ledger:
        return 0.0
    nets = [_net(r) for r in ledger]
    return sum(nets) / len(nets)


def _total_pnl(ledger: Sequence[dict]) -> float:
    if not ledger:
        return 0.0
    return sum(_net(r) for r in ledger)


def _relative_degradation(baseline: float, variant: float) -> float:
    """How much worse is ``variant`` than ``baseline``?

    Returns the relative drop in expectancy, clamped to [0, 1]. If the
    variant is better than baseline → 0.0 (no degradation). Uses
    max(|baseline|, 1.0) as denominator to avoid wild swings near zero.
    """
    if baseline <= 0.0:
        # If the baseline already lost money, "more loss" is the
        # degradation — relative to the magnitude.
        denom = max(abs(baseline), 1.0)
        drop = max(0.0, baseline - variant)  # variant lower than baseline
        return min(1.0, drop / denom)
    drop = baseline - variant
    if drop <= 0.0:
        return 0.0
    return min(1.0, drop / max(abs(baseline), 1.0))


# ─── Default no-op simulator ─────────────────────────────────────────────────


def _identity_simulator(ledger: Sequence[dict], *, params: dict,
                        slippage_bps: float, spread_bps: float
                        ) -> list[dict]:
    """Fallback simulator: subtract a deterministic transaction cost
    proportional to slippage + spread basis points from each trade.

    This is intentionally simple — it lets ``run_robustness_suite``
    produce a *meaningful but conservative* sensitivity test even when
    the caller has no historical replayer. Real callers replace it with
    a proper deterministic backtest replayer.

    NOTE: parameter perturbations have no effect under the identity
    simulator (we treat ``params`` as opaque). Callers wanting parameter
    sweeps must pass a real simulator.
    """
    bps = float(slippage_bps) + float(spread_bps)
    if bps <= 0:
        return [dict(r) for r in ledger]
    factor = bps / 10_000.0
    out: list[dict] = []
    for r in ledger:
        if not isinstance(r, dict):
            continue
        rr = dict(r)
        size = _safe_float(r.get("size_usd"), 0.0)
        if size <= 0:
            # Fall back to abs(net_pnl) as proxy for trade gross.
            size = max(abs(_net(r)), 0.0)
        rr["net_pnl"] = _net(r) - size * factor
        out.append(rr)
    return out


# ─── Parameter perturbation sweep ────────────────────────────────────────────


def _perturb_params(params: dict, key: str, delta: float) -> dict:
    """Return a new dict with ``params[key] *= (1 + delta)``."""
    out = dict(params)
    base = _safe_float(params.get(key))
    out[key] = base * (1.0 + delta)
    return out


def parameter_sweep(
    ledger: Sequence[dict],
    *,
    params: dict | None,
    simulator: Callable[..., list[dict]] | None,
) -> dict[str, dict[str, float]]:
    """Per-parameter ±10% / ±20% sweep.

    Returns a dict of the form::

        {
            "<param_name>": {
                "baseline_expectancy":    <float>,
                "sensitivity":            <float>,
                "max_relative_drop":      <float>,
                "fragility_detected":     <bool>,
                "variants": {
                    "+10%": <expectancy_after_perturbation>,
                    ...
                },
            },
            ...
        }

    If ``params`` is empty/None, returns ``{}`` immediately.
    """
    if not params:
        return {}
    sim = simulator or _identity_simulator
    baseline_exp = _expectancy(ledger)
    out: dict[str, dict[str, float]] = {}

    for key in list(params.keys()):
        if not isinstance(key, str):
            continue
        variants: dict[str, float] = {}
        max_drop = 0.0
        for delta in PARAM_PERTURBATIONS:
            try:
                perturbed = _perturb_params(params, key, delta)
                sim_ledger = sim(ledger, params=perturbed,
                                 slippage_bps=0.0, spread_bps=0.0)
                exp_v = _expectancy(sim_ledger)
            except Exception:
                exp_v = baseline_exp  # fail-soft, no degradation
            label = f"{'+' if delta >= 0 else ''}{int(delta * 100)}%"
            variants[label] = round(exp_v, 6)
            drop = _relative_degradation(baseline_exp, exp_v)
            if drop > max_drop:
                max_drop = drop

        # Sensitivity = spread across variants / max(|baseline|, 1)
        try:
            spread = (max(variants.values()) - min(variants.values())) \
                if variants else 0.0
        except ValueError:
            spread = 0.0
        sensitivity = spread / max(abs(baseline_exp), 1.0)

        out[key] = {
            "baseline_expectancy":  round(baseline_exp, 6),
            "sensitivity":          round(sensitivity, 6),
            "max_relative_drop":    round(max_drop, 6),
            "fragility_detected":   bool(
                max_drop > DEGRADATION_FRAGILITY_THRESHOLD),
            "variants":             variants,
        }
    return out


# ─── Cost sensitivity ────────────────────────────────────────────────────────


def cost_sensitivity(
    ledger: Sequence[dict],
    *,
    simulator: Callable[..., list[dict]] | None = None,
    params: dict | None = None,
) -> dict[str, Any]:
    """Run slippage + spread sweeps. Returns dict of expectancy by bps."""
    sim = simulator or _identity_simulator
    baseline_exp = _expectancy(ledger)
    slip: dict[str, float] = {}
    spread: dict[str, float] = {}
    max_slip_drop = 0.0
    max_spread_drop = 0.0
    p = params or {}

    for bps in SLIPPAGE_BPS_SAMPLES:
        try:
            sim_l = sim(ledger, params=p, slippage_bps=bps,
                        spread_bps=0.0)
            exp_v = _expectancy(sim_l)
        except Exception:
            exp_v = baseline_exp
        slip[f"{bps}bps"] = round(exp_v, 6)
        drop = _relative_degradation(baseline_exp, exp_v)
        if drop > max_slip_drop:
            max_slip_drop = drop

    for bps in SPREAD_BPS_SAMPLES:
        try:
            sim_l = sim(ledger, params=p, slippage_bps=0.0,
                        spread_bps=bps)
            exp_v = _expectancy(sim_l)
        except Exception:
            exp_v = baseline_exp
        spread[f"{bps}bps"] = round(exp_v, 6)
        drop = _relative_degradation(baseline_exp, exp_v)
        if drop > max_spread_drop:
            max_spread_drop = drop

    return {
        "baseline_expectancy":  round(baseline_exp, 6),
        "slippage":             slip,
        "spread":               spread,
        "max_slippage_drop":    round(max_slip_drop, 6),
        "max_spread_drop":      round(max_spread_drop, 6),
        "slippage_fragility":   bool(
            max_slip_drop > SLIPPAGE_FRAGILITY_THRESHOLD),
        "spread_fragility":     bool(
            max_spread_drop > SPREAD_FRAGILITY_THRESHOLD),
    }


# ─── Data splits ─────────────────────────────────────────────────────────────


def time_window_splits(ledger: Sequence[dict],
                       splits: int = 3) -> dict[str, Any]:
    """Split the ledger into ``splits`` contiguous windows and report
    expectancy in each. Reveals time-decay.
    """
    splits = max(2, int(splits))
    n = len(ledger or [])
    if n < splits * 2:
        return {"buckets": {}, "max_relative_drop": 0.0,
                "fragility_detected": False}
    chunk = n // splits
    baseline = _expectancy(ledger)
    buckets: dict[str, float] = {}
    max_drop = 0.0
    for i in range(splits):
        start = i * chunk
        end = n if i == splits - 1 else (i + 1) * chunk
        sub = ledger[start:end]
        exp_v = _expectancy(sub)
        buckets[f"window_{i+1}_of_{splits}"] = round(exp_v, 6)
        drop = _relative_degradation(baseline, exp_v)
        if drop > max_drop:
            max_drop = drop
    return {
        "buckets":              buckets,
        "max_relative_drop":    round(max_drop, 6),
        "fragility_detected":   bool(
            max_drop > TIME_SPLIT_FRAGILITY_THRESHOLD),
    }


def _group_by(ledger: Sequence[dict], key: str) -> dict[str, list[dict]]:
    """Group records by a string key. Records missing the key go to ``""``.
    """
    groups: dict[str, list[dict]] = {}
    for r in ledger:
        if not isinstance(r, dict):
            continue
        v = r.get(key, "")
        if v is None:
            v = ""
        groups.setdefault(str(v), []).append(r)
    return groups


def regime_splits(ledger: Sequence[dict]) -> dict[str, Any]:
    """Per-regime expectancy + fragility test.

    Skips the empty/unknown regime label. Returns sensible empty dict if
    there is no ``regime`` field in any record.
    """
    groups = _group_by(ledger, "regime")
    # Drop empty / "unknown".
    groups = {g: recs for g, recs in groups.items()
              if g and g.lower() != "unknown"}
    if not groups:
        return {"buckets": {}, "max_relative_drop": 0.0,
                "fragility_detected": False}
    baseline = _expectancy(ledger)
    buckets: dict[str, float] = {}
    max_drop = 0.0
    for g, recs in groups.items():
        exp_v = _expectancy(recs)
        buckets[g] = round(exp_v, 6)
        drop = _relative_degradation(baseline, exp_v)
        if drop > max_drop:
            max_drop = drop
    return {
        "buckets":              buckets,
        "max_relative_drop":    round(max_drop, 6),
        "fragility_detected":   bool(
            max_drop > REGIME_SPLIT_FRAGILITY_THRESHOLD),
    }


def symbol_splits(ledger: Sequence[dict]) -> dict[str, Any]:
    """Per-symbol expectancy + fragility test."""
    groups = _group_by(ledger, "symbol")
    groups = {g: recs for g, recs in groups.items() if g}
    if not groups:
        return {"buckets": {}, "max_relative_drop": 0.0,
                "fragility_detected": False}
    baseline = _expectancy(ledger)
    buckets: dict[str, float] = {}
    max_drop = 0.0
    for g, recs in groups.items():
        exp_v = _expectancy(recs)
        buckets[g] = round(exp_v, 6)
        drop = _relative_degradation(baseline, exp_v)
        if drop > max_drop:
            max_drop = drop
    return {
        "buckets":              buckets,
        "max_relative_drop":    round(max_drop, 6),
        "fragility_detected":   bool(
            max_drop > SYMBOL_SPLIT_FRAGILITY_THRESHOLD),
    }


# ─── Drop-one ablations ──────────────────────────────────────────────────────


def drop_one_best_trade(ledger: Sequence[dict]) -> dict[str, Any]:
    """Drop the single best trade and report expectancy delta."""
    if not ledger:
        return {"baseline_expectancy": 0.0, "after_drop_expectancy": 0.0,
                "relative_drop": 0.0, "dominant_trade": False}
    nets = [_net(r) for r in ledger]
    baseline = sum(nets) / len(nets)
    idx = nets.index(max(nets))
    remaining = nets[:idx] + nets[idx + 1:]
    after = (sum(remaining) / len(remaining)) if remaining else 0.0
    # "Dominant" if the single trade was > OVERFIT_SUSPICION_PCT of total
    # positive contribution.
    total_pos = sum(p for p in nets if p > 0)
    best = max(nets)
    dominant = bool(total_pos > 0 and best > 0
                    and (best / total_pos) >= OVERFIT_SUSPICION_PCT)
    return {
        "baseline_expectancy":      round(baseline, 6),
        "after_drop_expectancy":    round(after, 6),
        "relative_drop":            round(
            _relative_degradation(baseline, after), 6),
        "dominant_trade":           dominant,
        "best_trade_pnl":           round(best, 6),
        "best_trade_share_of_pos":  round(
            (best / total_pos) if total_pos > 0 else 0.0, 6),
    }


def drop_one_best_day(ledger: Sequence[dict]) -> dict[str, Any]:
    """Drop the single best trading day (by absolute PnL) and report
    expectancy delta. Requires a ``closed_at`` ISO timestamp string on
    each record; otherwise returns a neutral result.
    """
    if not ledger:
        return {"baseline_expectancy": 0.0, "after_drop_expectancy": 0.0,
                "relative_drop": 0.0, "dominant_day": False}
    daily: dict[str, float] = {}
    for r in ledger:
        if not isinstance(r, dict):
            continue
        ts = r.get("closed_at") or r.get("date") or ""
        day = str(ts)[:10] if ts else ""
        if not day:
            continue
        daily[day] = daily.get(day, 0.0) + _net(r)
    if not daily:
        return {"baseline_expectancy": _expectancy(ledger),
                "after_drop_expectancy": _expectancy(ledger),
                "relative_drop": 0.0, "dominant_day": False}
    best_day = max(daily, key=lambda k: daily[k])
    best_pnl = daily[best_day]
    total_pos = sum(v for v in daily.values() if v > 0)
    dominant = bool(total_pos > 0 and best_pnl > 0
                    and (best_pnl / total_pos) >= SINGLE_DAY_DEPENDENCE_PCT)
    baseline = _expectancy(ledger)
    remaining = [r for r in ledger
                 if str(r.get("closed_at") or r.get("date") or "")[:10]
                 != best_day]
    after = _expectancy(remaining) if remaining else 0.0
    return {
        "baseline_expectancy":     round(baseline, 6),
        "after_drop_expectancy":   round(after, 6),
        "relative_drop":           round(
            _relative_degradation(baseline, after), 6),
        "dominant_day":            dominant,
        "best_day":                best_day,
        "best_day_pnl":            round(best_pnl, 6),
        "best_day_share_of_pos":   round(
            (best_pnl / total_pos) if total_pos > 0 else 0.0, 6),
    }


def drop_one_best_symbol(ledger: Sequence[dict]) -> dict[str, Any]:
    """Drop the single best-performing symbol and report expectancy delta.
    """
    if not ledger:
        return {"baseline_expectancy": 0.0, "after_drop_expectancy": 0.0,
                "relative_drop": 0.0, "dominant_symbol": False}
    per_symbol: dict[str, float] = {}
    for r in ledger:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or "")
        if not sym:
            continue
        per_symbol[sym] = per_symbol.get(sym, 0.0) + _net(r)
    if not per_symbol:
        return {"baseline_expectancy": _expectancy(ledger),
                "after_drop_expectancy": _expectancy(ledger),
                "relative_drop": 0.0, "dominant_symbol": False}
    best_sym = max(per_symbol, key=lambda k: per_symbol[k])
    best_pnl = per_symbol[best_sym]
    total_pos = sum(v for v in per_symbol.values() if v > 0)
    dominant = bool(
        total_pos > 0 and best_pnl > 0
        and (best_pnl / total_pos) >= SINGLE_SYMBOL_DEPENDENCE_PCT)
    baseline = _expectancy(ledger)
    remaining = [r for r in ledger if str(r.get("symbol") or "") != best_sym]
    after = _expectancy(remaining) if remaining else 0.0
    return {
        "baseline_expectancy":     round(baseline, 6),
        "after_drop_expectancy":   round(after, 6),
        "relative_drop":           round(
            _relative_degradation(baseline, after), 6),
        "dominant_symbol":         dominant,
        "best_symbol":             best_sym,
        "best_symbol_pnl":         round(best_pnl, 6),
        "best_symbol_share_of_pos": round(
            (best_pnl / total_pos) if total_pos > 0 else 0.0, 6),
    }


# ─── Public API: full suite ──────────────────────────────────────────────────


def run_robustness_suite(
    strategy: str,
    ledger: Sequence[dict],
    *,
    params: dict | None = None,
    simulator: Callable[..., list[dict]] | None = None,
) -> dict[str, Any]:
    """Run the full robustness sandbox for one strategy.

    Parameters
    ----------
    strategy : str
        Strategy name (echoed in the output for audit correlation).
    ledger : sequence of dicts
        Trade records. Must contain at least ``net_pnl``. Optional
        fields ``symbol`` / ``regime`` / ``closed_at`` enable the
        corresponding split.
    params : dict, optional
        Strategy parameters keyed by name. Used for sweeps; ignored if
        ``None`` or empty.
    simulator : callable, optional
        Deterministic re-simulator. See module docstring. Defaults to a
        conservative identity simulator that subtracts proportional
        costs only.

    Returns
    -------
    dict with keys:
      - strategy
      - n_trades
      - baseline_expectancy / baseline_total_pnl
      - parameter_sensitivity        (dict)
      - cost_sensitivity             (dict)
      - time_window_splits           (dict)
      - regime_splits                (dict)
      - symbol_splits                (dict)
      - drop_one_best_trade          (dict)
      - drop_one_best_day            (dict)
      - drop_one_best_symbol         (dict)
      - fragility_warnings           (list[str])
      - max_relative_degradation     (float)
      - robustness_score             (float, 0..1)
      - overfit_suspicion            (bool)
      - dependency_on_one_symbol     (bool)
      - dependency_on_one_day        (bool)
      - dependency_on_one_regime     (bool)
      - sandbox_never_optimizes      (bool, echoes invariant)
      - sandbox_never_mutates_runtime (bool, echoes invariant)
      - error                         (optional)
    """
    result: dict[str, Any] = {
        "strategy":                       strategy,
        "n_trades":                       len(ledger or []),
        "baseline_expectancy":            0.0,
        "baseline_total_pnl":             0.0,
        "parameter_sensitivity":          {},
        "cost_sensitivity":               {},
        "time_window_splits":             {},
        "regime_splits":                  {},
        "symbol_splits":                  {},
        "drop_one_best_trade":            {},
        "drop_one_best_day":              {},
        "drop_one_best_symbol":           {},
        "fragility_warnings":             [],
        "max_relative_degradation":       0.0,
        "robustness_score":               1.0,
        "overfit_suspicion":              False,
        "dependency_on_one_symbol":       False,
        "dependency_on_one_day":          False,
        "dependency_on_one_regime":       False,
        "sandbox_never_optimizes":        SANDBOX_NEVER_OPTIMIZES,
        "sandbox_never_mutates_runtime":  SANDBOX_NEVER_MUTATES_RUNTIME,
    }

    try:
        # Snapshot ledger length so we can later assert no mutation.
        _initial_len = len(ledger or [])
        _initial_first = (ledger[0] if ledger else None)

        result["baseline_expectancy"] = round(_expectancy(ledger), 6)
        result["baseline_total_pnl"] = round(_total_pnl(ledger), 6)

        # Run all sweeps.
        result["parameter_sensitivity"] = parameter_sweep(
            ledger, params=params, simulator=simulator)
        result["cost_sensitivity"] = cost_sensitivity(
            ledger, simulator=simulator, params=params)
        result["time_window_splits"] = time_window_splits(ledger)
        result["regime_splits"] = regime_splits(ledger)
        result["symbol_splits"] = symbol_splits(ledger)
        result["drop_one_best_trade"] = drop_one_best_trade(ledger)
        result["drop_one_best_day"] = drop_one_best_day(ledger)
        result["drop_one_best_symbol"] = drop_one_best_symbol(ledger)

        # Aggregate fragility warnings + max degradation.
        warns: list[str] = []
        degs: list[float] = []

        # parameter sweep
        for k, sub in result["parameter_sensitivity"].items():
            if sub.get("fragility_detected"):
                warns.append(
                    f"param '{k}' fragile: max_relative_drop "
                    f"{sub.get('max_relative_drop'):.0%}")
            degs.append(_safe_float(sub.get("max_relative_drop")))

        cs = result["cost_sensitivity"]
        if cs.get("slippage_fragility"):
            warns.append(
                f"slippage fragile: max drop "
                f"{cs.get('max_slippage_drop'):.0%}")
        if cs.get("spread_fragility"):
            warns.append(
                f"spread fragile: max drop "
                f"{cs.get('max_spread_drop'):.0%}")
        degs.append(_safe_float(cs.get("max_slippage_drop")))
        degs.append(_safe_float(cs.get("max_spread_drop")))

        for axis_name, key in (
                ("time-window", "time_window_splits"),
                ("regime", "regime_splits"),
                ("symbol", "symbol_splits")):
            sub = result[key]
            if sub.get("fragility_detected"):
                warns.append(
                    f"{axis_name} fragile: max drop "
                    f"{sub.get('max_relative_drop'):.0%}")
            degs.append(_safe_float(sub.get("max_relative_drop")))

        # Overfit suspicion + dependency flags
        trade_drop = result["drop_one_best_trade"]
        if trade_drop.get("dominant_trade"):
            warns.append(
                "single trade dominates positive PnL "
                f"({trade_drop.get('best_trade_share_of_pos'):.0%})")
        result["overfit_suspicion"] = bool(
            trade_drop.get("dominant_trade", False))

        sym_drop = result["drop_one_best_symbol"]
        result["dependency_on_one_symbol"] = bool(
            sym_drop.get("dominant_symbol", False))
        if result["dependency_on_one_symbol"]:
            warns.append(
                f"single symbol {sym_drop.get('best_symbol')} "
                f"dominates "
                f"({sym_drop.get('best_symbol_share_of_pos'):.0%})")

        day_drop = result["drop_one_best_day"]
        result["dependency_on_one_day"] = bool(
            day_drop.get("dominant_day", False))
        if result["dependency_on_one_day"]:
            warns.append(
                f"single day {day_drop.get('best_day')} dominates "
                f"({day_drop.get('best_day_share_of_pos'):.0%})")

        # Regime dependence — flag if positive PnL concentrates ≥70% in one
        regime_buckets = result["regime_splits"].get("buckets") or {}
        regime_dep = False
        if regime_buckets:
            pos_only = {k: v for k, v in regime_buckets.items() if v > 0}
            total_pos = sum(pos_only.values())
            if total_pos > 0:
                top_share = max(pos_only.values()) / total_pos
                if top_share >= SINGLE_REGIME_DEPENDENCE_PCT:
                    regime_dep = True
                    top_label = max(pos_only, key=lambda k: pos_only[k])
                    warns.append(
                        f"single regime {top_label} dominates "
                        f"({top_share:.0%})")
        result["dependency_on_one_regime"] = regime_dep

        max_deg = max(degs) if degs else 0.0
        result["max_relative_degradation"] = round(max_deg, 6)
        score = max(0.0, min(1.0, 1.0 - max_deg))
        result["robustness_score"] = round(score, 6)
        result["fragility_warnings"] = warns

        # Final sandbox integrity assertion: we have not mutated the
        # original ledger list or its first record's net_pnl.
        if isinstance(ledger, list) and len(ledger) != _initial_len:
            raise RuntimeError(
                "sandbox integrity broken — ledger length changed")
        if _initial_first is not None and ledger \
                and _net(ledger[0]) != _net(_initial_first):
            raise RuntimeError(
                "sandbox integrity broken — first record mutated")

        return result
    except Exception as exc:  # fail-soft
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["robustness_score"] = 0.0
        return result


__all__ = [
    # invariants
    "SANDBOX_NEVER_OPTIMIZES", "SANDBOX_NEVER_MUTATES_RUNTIME",
    # thresholds
    "PARAM_PERTURBATIONS", "SLIPPAGE_BPS_SAMPLES", "SPREAD_BPS_SAMPLES",
    "DEGRADATION_FRAGILITY_THRESHOLD", "SLIPPAGE_FRAGILITY_THRESHOLD",
    "SPREAD_FRAGILITY_THRESHOLD", "TIME_SPLIT_FRAGILITY_THRESHOLD",
    "REGIME_SPLIT_FRAGILITY_THRESHOLD", "SYMBOL_SPLIT_FRAGILITY_THRESHOLD",
    "OVERFIT_SUSPICION_PCT", "SINGLE_SYMBOL_DEPENDENCE_PCT",
    "SINGLE_DAY_DEPENDENCE_PCT", "SINGLE_REGIME_DEPENDENCE_PCT",
    # public API
    "parameter_sweep", "cost_sensitivity",
    "time_window_splits", "regime_splits", "symbol_splits",
    "drop_one_best_trade", "drop_one_best_day", "drop_one_best_symbol",
    "run_robustness_suite",
]
