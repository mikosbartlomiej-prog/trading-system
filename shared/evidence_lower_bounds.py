"""v3.20.0 (2026-06-04) — ETAP 4 — Strategy Evidence Lower Bounds.

Closes audit-board STRAT-003 evidence-rigor follow-up: a strategy must
prove its edge with *statistical lower bounds*, not point estimates. A
mean win-rate of 0.55 over n=18 trades is not evidence — the 95% Wilson
lower bound for that sample is 0.34, which is below chance after costs.

The module is the deterministic statistics layer that sits between the
paper ledger and ``strategy_quality_gate.classify_strategy(...)``. It
NEVER mutates the runtime, NEVER calls the broker, NEVER calls a paid
API, and NEVER flips ``EDGE_GATE_ENABLED``.

DESIGN PRINCIPLES
-----------------
1. Pure function. Input = list of trade records, output = metrics dict.
2. Deterministic bootstrap. ``seed = 42 + stable_hash(strategy_name)``.
   The same ledger + same strategy name yields the exact same numbers.
3. No external numerical libraries. We rely on ``random`` + ``math``
   only so this works on the free-tier runner.
4. Conservative defaults. Missing data → ``EVIDENCE_TOO_WEAK``.
5. Fail-soft. Any internal error → an explicit ``error`` field on the
   result dict and a ``status = EVIDENCE_TOO_WEAK`` fallback.

PUBLIC API
----------
``compute_strategy_evidence_bounds(strategy, ledger, *, bootstrap_n=1000)``
    Returns the full dict of lower-bound metrics for a single strategy.

``classify_strategy_evidence(ledger, strategy_name)``
    Returns one of the status strings in ``EVIDENCE_STATUSES``.

STATUS LADDER
-------------
- ``EVIDENCE_TOO_WEAK``         — n < 50 OR Wilson WR lower bound < 0.40.
- ``EVIDENCE_IMPROVING``        — 20 ≤ n < 50 AND mean WR ≥ 0.50.
- ``EVIDENCE_ROBUST_CANDIDATE`` — n ≥ 50 AND PF lower bound ≥ 1.3 AND
                                  expectancy lower bound > 0.
- ``EVIDENCE_DEGRADING``        — last 20 trades worse than first 20
                                  (n ≥ 40 required for the comparison).
- ``EVIDENCE_REJECT``           — PF mean ≥ 1.3 but PF lower bound < 1.0
                                  (mean inflated by tail wins; not robust).

NOTE: ``classify_strategy_evidence`` is intentionally exposed for later
wiring into ``strategy_quality_gate``. This file does NOT modify the
gate today — that wiring lives in a separate ETAP and is gated on
operator review of the audit-board outcome.
"""

from __future__ import annotations

import hashlib
import math
import random
import statistics
from typing import Any, Iterable, Sequence

# ─── Statuses (closed enum) ──────────────────────────────────────────────────

EVIDENCE_TOO_WEAK         = "EVIDENCE_TOO_WEAK"
EVIDENCE_IMPROVING        = "EVIDENCE_IMPROVING"
EVIDENCE_ROBUST_CANDIDATE = "EVIDENCE_ROBUST_CANDIDATE"
EVIDENCE_DEGRADING        = "EVIDENCE_DEGRADING"
EVIDENCE_REJECT           = "EVIDENCE_REJECT"

EVIDENCE_STATUSES: frozenset[str] = frozenset({
    EVIDENCE_TOO_WEAK,
    EVIDENCE_IMPROVING,
    EVIDENCE_ROBUST_CANDIDATE,
    EVIDENCE_DEGRADING,
    EVIDENCE_REJECT,
})

# ─── Thresholds (deterministic, exported for tests) ──────────────────────────

MIN_N_FOR_ROBUST          = 50
MIN_N_FOR_IMPROVING       = 20
MIN_WR_LB_NOT_TOO_WEAK    = 0.40
MIN_MEAN_WR_FOR_IMPROVING = 0.50
MIN_PF_LB_FOR_ROBUST      = 1.30
MIN_EXP_LB_FOR_ROBUST     = 0.0   # strictly positive
MIN_PF_MEAN_FOR_REJECT    = 1.30
MAX_PF_LB_FOR_REJECT      = 1.00

WILSON_Z                  = 1.96   # 95% two-sided
BOOTSTRAP_RESAMPLES       = 1000
BOOTSTRAP_LOWER_PCT       = 5.0    # 5th percentile
WORST_WINDOW              = 20
MIN_N_FOR_DEGRADATION     = 40     # need ≥ 40 to compare first 20 vs last 20

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:   # NaN
            return default
        if v == float("inf") or v == float("-inf"):
            return default
        return v
    except (TypeError, ValueError):
        return default


def _stable_hash(name: str) -> int:
    """Deterministic integer hash (Python's ``hash`` is randomised per run).

    SHA-256 first 8 bytes → big-endian int. Stable across processes.
    """
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def _seed_for(strategy: str) -> int:
    """``seed = 42 + stable_hash(strategy_name)`` per spec."""
    return 42 + (_stable_hash(strategy or "") & 0x7FFFFFFF)


def _extract_net_pnls(ledger: Sequence[dict]) -> list[float]:
    """Pull ``net_pnl`` from each record, in order. Skip non-numeric."""
    out: list[float] = []
    if not ledger:
        return out
    for rec in ledger:
        if not isinstance(rec, dict):
            continue
        v = rec.get("net_pnl")
        if v is None:
            v = rec.get("pnl_net")
        if v is None:
            v = rec.get("pnl")
        try:
            f = float(v)
            if f != f:
                continue
            if f == float("inf") or f == float("-inf"):
                continue
            out.append(f)
        except (TypeError, ValueError):
            continue
    return out


# ─── Wilson 95% lower bound ──────────────────────────────────────────────────


def wilson_lower_bound(wins: int, n: int, z: float = WILSON_Z) -> float:
    """Wilson 95% (two-sided) lower confidence bound on a binomial p.

    Formula (per spec):

        (p + z²/(2n) - z·sqrt((p(1-p) + z²/(4n)) / n)) / (1 + z²/n)

    Clamps to [0, 1]. Returns 0.0 if n == 0.
    """
    n = int(n)
    wins = int(wins)
    if n <= 0:
        return 0.0
    p = wins / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = p + z2 / (2.0 * n)
    radicand = (p * (1.0 - p) + z2 / (4.0 * n)) / n
    if radicand < 0.0:
        radicand = 0.0
    half = z * math.sqrt(radicand)
    lb = (centre - half) / denom
    if lb < 0.0:
        return 0.0
    if lb > 1.0:
        return 1.0
    return lb


# ─── Bootstrap utilities ─────────────────────────────────────────────────────


def _bootstrap_indices(rng: random.Random, n: int) -> list[int]:
    """One resample-with-replacement of ``n`` indices from [0, n)."""
    return [rng.randrange(n) for _ in range(n)]


def _percentile(values: list[float], pct: float) -> float:
    """Simple percentile (linear interpolation). ``pct`` is 0..100."""
    if not values:
        return 0.0
    if pct <= 0:
        return min(values)
    if pct >= 100:
        return max(values)
    s = sorted(values)
    k = (pct / 100.0) * (len(s) - 1)
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return s[lo]
    frac = k - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def _profit_factor(nets: Sequence[float]) -> float:
    """Profit factor = sum(wins) / |sum(losses)|. Mirrors paper_experiment."""
    if not nets:
        return 0.0
    gross_win = sum(p for p in nets if p > 0)
    gross_loss = -sum(p for p in nets if p < 0)
    if gross_loss > 0:
        return gross_win / gross_loss
    if gross_win > 0:
        return 999.0
    return 0.0


def _expectancy(nets: Sequence[float]) -> float:
    """Mean net P&L per trade."""
    if not nets:
        return 0.0
    return sum(nets) / len(nets)


def _max_drawdown(nets: Sequence[float]) -> float:
    """Peak-to-trough drawdown as fraction of peak (0..1)."""
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in nets:
        cum += p
        if cum > peak:
            peak = cum
        if peak > 0:
            dd = (peak - cum) / peak
            if dd > max_dd:
                max_dd = dd
        elif cum < 0:
            denom = max(abs(cum), 1.0)
            dd = abs(cum) / denom
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _worst_rolling_window(nets: Sequence[float], window: int) -> float:
    """Worst sum over any contiguous ``window`` of size ``window`` (or shorter
    when len(nets) < window). Returns 0.0 on empty input.
    """
    if not nets:
        return 0.0
    if len(nets) <= window:
        return sum(nets)
    worst = float("inf")
    rolling = sum(nets[:window])
    if rolling < worst:
        worst = rolling
    for i in range(window, len(nets)):
        rolling += nets[i] - nets[i - window]
        if rolling < worst:
            worst = rolling
    return worst


# ─── Bootstrap of full metric set ────────────────────────────────────────────


def _bootstrap_metrics(nets: list[float], seed: int,
                       *, resamples: int = BOOTSTRAP_RESAMPLES
                       ) -> dict[str, float]:
    """Run deterministic bootstrap. Returns lower bounds + stability stats.

    Output keys:
      - profit_factor_lower_bound
      - expectancy_lower_bound
      - drawdown_upper_bound
      - bootstrap_outcome_stability
      - bootstrap_resamples (echo)
    """
    if not nets or resamples <= 0:
        return {
            "profit_factor_lower_bound":    0.0,
            "expectancy_lower_bound":       0.0,
            "drawdown_upper_bound":         0.0,
            "bootstrap_outcome_stability":  0.0,
            "bootstrap_resamples":          0,
        }

    rng = random.Random(seed)
    n = len(nets)
    pf_samples: list[float] = []
    exp_samples: list[float] = []
    dd_samples: list[float] = []
    sum_samples: list[float] = []

    for _ in range(resamples):
        idxs = _bootstrap_indices(rng, n)
        sample = [nets[i] for i in idxs]
        pf_samples.append(_profit_factor(sample))
        exp_samples.append(_expectancy(sample))
        dd_samples.append(_max_drawdown(sample))
        sum_samples.append(sum(sample))

    pf_lb = _percentile(pf_samples, BOOTSTRAP_LOWER_PCT)
    exp_lb = _percentile(exp_samples, BOOTSTRAP_LOWER_PCT)
    dd_ub = _percentile(dd_samples, 100.0 - BOOTSTRAP_LOWER_PCT)

    # outcome stability: relative spread of cumulative P&L. We use
    # ``stdev / max(|mean|, 1)`` so we don't divide by ~0 for marginal
    # strategies (purely descriptive — lower is more stable).
    mean_sum = statistics.fmean(sum_samples) if sum_samples else 0.0
    try:
        std_sum = statistics.pstdev(sum_samples) if len(sum_samples) > 1 else 0.0
    except statistics.StatisticsError:
        std_sum = 0.0
    denom = max(abs(mean_sum), 1.0)
    stability = std_sum / denom

    return {
        "profit_factor_lower_bound":    round(pf_lb, 6),
        "expectancy_lower_bound":       round(exp_lb, 6),
        "drawdown_upper_bound":         round(dd_ub, 6),
        "bootstrap_outcome_stability":  round(stability, 6),
        "bootstrap_resamples":          resamples,
    }


# ─── Public API: per-strategy evidence dict ──────────────────────────────────


def compute_strategy_evidence_bounds(
    strategy: str,
    ledger: Sequence[dict],
    *,
    bootstrap_n: int = BOOTSTRAP_RESAMPLES,
) -> dict[str, Any]:
    """Compute all evidence lower bounds for a single strategy.

    Parameters
    ----------
    strategy : str
        Strategy name. Used as part of the bootstrap seed so two
        different strategies with the same ledger receive different
        bootstrap draws (mirrors normal Monte-Carlo practice).
    ledger : sequence of dicts
        Trade records. We extract ``net_pnl`` (or ``pnl_net`` / ``pnl``)
        from each. Records without a usable number are skipped.
    bootstrap_n : int
        Number of resamples. Spec mandates 1000.

    Returns
    -------
    dict with keys:
      - strategy
      - n_closed, wins, losses
      - win_rate_mean
      - win_rate_lower_cb     (Wilson 95% LB)
      - profit_factor_mean
      - profit_factor_lower_bound
      - expectancy_mean
      - expectancy_lower_bound
      - max_drawdown_mean
      - drawdown_upper_bound
      - bootstrap_outcome_stability
      - worst_20_trade_window
      - probability_of_negative_expectancy
      - sample_size_sufficiency      (bool, n ≥ 50)
      - first_20_mean_net_pnl
      - last_20_mean_net_pnl
      - last_20_worse_than_first_20  (bool)
      - bootstrap_seed
      - bootstrap_resamples
      - status                       (one of EVIDENCE_STATUSES)
      - error (optional, string if fail-soft fallback hit)
    """
    out: dict[str, Any] = {
        "strategy": strategy,
        "n_closed": 0,
        "wins": 0,
        "losses": 0,
        "win_rate_mean": 0.0,
        "win_rate_lower_cb": 0.0,
        "profit_factor_mean": 0.0,
        "profit_factor_lower_bound": 0.0,
        "expectancy_mean": 0.0,
        "expectancy_lower_bound": 0.0,
        "max_drawdown_mean": 0.0,
        "drawdown_upper_bound": 0.0,
        "bootstrap_outcome_stability": 0.0,
        "worst_20_trade_window": 0.0,
        "probability_of_negative_expectancy": 1.0,
        "sample_size_sufficiency": False,
        "first_20_mean_net_pnl": 0.0,
        "last_20_mean_net_pnl": 0.0,
        "last_20_worse_than_first_20": False,
        "bootstrap_seed": _seed_for(strategy or ""),
        "bootstrap_resamples": int(bootstrap_n),
        "status": EVIDENCE_TOO_WEAK,
    }

    try:
        nets = _extract_net_pnls(ledger or [])
        n = len(nets)
        out["n_closed"] = n
        if n == 0:
            return out

        wins_n = sum(1 for p in nets if p > 0)
        losses_n = sum(1 for p in nets if p < 0)
        out["wins"] = wins_n
        out["losses"] = losses_n
        out["win_rate_mean"] = round(wins_n / n, 6)
        out["win_rate_lower_cb"] = round(wilson_lower_bound(wins_n, n), 6)
        out["profit_factor_mean"] = round(_profit_factor(nets), 6)
        out["expectancy_mean"] = round(_expectancy(nets), 6)
        out["max_drawdown_mean"] = round(_max_drawdown(nets), 6)
        out["worst_20_trade_window"] = round(
            _worst_rolling_window(nets, WORST_WINDOW), 6)
        out["sample_size_sufficiency"] = n >= MIN_N_FOR_ROBUST

        # First-20 vs last-20 degradation comparison.
        if n >= MIN_N_FOR_DEGRADATION:
            first20 = nets[:WORST_WINDOW]
            last20 = nets[-WORST_WINDOW:]
            f_mean = sum(first20) / len(first20)
            l_mean = sum(last20) / len(last20)
            out["first_20_mean_net_pnl"] = round(f_mean, 6)
            out["last_20_mean_net_pnl"] = round(l_mean, 6)
            out["last_20_worse_than_first_20"] = bool(l_mean < f_mean)

        # Bootstrap section.
        boot = _bootstrap_metrics(nets, _seed_for(strategy or ""),
                                  resamples=int(bootstrap_n))
        out["profit_factor_lower_bound"] = boot["profit_factor_lower_bound"]
        out["expectancy_lower_bound"] = boot["expectancy_lower_bound"]
        out["drawdown_upper_bound"] = boot["drawdown_upper_bound"]
        out["bootstrap_outcome_stability"] = boot[
            "bootstrap_outcome_stability"]

        # P(expectancy <= 0) approximated from bootstrap expectancy
        # distribution. We re-derive it cheaply by re-running a small
        # deterministic estimate (re-use stability seed).
        out["probability_of_negative_expectancy"] = _prob_neg_expectancy(
            nets, _seed_for(strategy or ""), int(bootstrap_n))

        out["status"] = _classify_from_summary(out)
        return out
    except Exception as exc:  # fail-soft
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["status"] = EVIDENCE_TOO_WEAK
        return out


def _prob_neg_expectancy(nets: list[float], seed: int,
                         resamples: int) -> float:
    """P(bootstrap-sample expectancy ≤ 0). Diagnostic only."""
    if not nets or resamples <= 0:
        return 1.0
    rng = random.Random(seed ^ 0xA5A5A5A5)
    n = len(nets)
    neg = 0
    for _ in range(resamples):
        idxs = [rng.randrange(n) for _ in range(n)]
        s = sum(nets[i] for i in idxs)
        if s <= 0:
            neg += 1
    return round(neg / resamples, 6)


# ─── Classifier ──────────────────────────────────────────────────────────────


def _classify_from_summary(summary: dict[str, Any]) -> str:
    """Map a populated summary dict to one of EVIDENCE_STATUSES.

    Logic order:
      1. EVIDENCE_REJECT: PF mean ≥ 1.3 AND PF LB < 1.0 (tail-driven mean).
      2. EVIDENCE_TOO_WEAK: n < 50 OR Wilson WR LB < 0.40.
      3. EVIDENCE_DEGRADING: n ≥ 40 AND last_20 < first_20.
      4. EVIDENCE_IMPROVING: 20 ≤ n < 50 AND mean WR ≥ 0.50.
      5. EVIDENCE_ROBUST_CANDIDATE: n ≥ 50 AND PF LB ≥ 1.3 AND exp LB > 0.
      6. Otherwise EVIDENCE_TOO_WEAK (conservative default).
    """
    n = int(summary.get("n_closed", 0))
    wr_mean = _safe_float(summary.get("win_rate_mean"))
    wr_lb = _safe_float(summary.get("win_rate_lower_cb"))
    pf_mean = _safe_float(summary.get("profit_factor_mean"))
    pf_lb = _safe_float(summary.get("profit_factor_lower_bound"))
    exp_lb = _safe_float(summary.get("expectancy_lower_bound"))
    degrading_flag = bool(summary.get("last_20_worse_than_first_20"))

    # 1. PF inflated by tail wins → reject.
    if (pf_mean >= MIN_PF_MEAN_FOR_REJECT
            and pf_lb < MAX_PF_LB_FOR_REJECT
            and n >= MIN_N_FOR_IMPROVING):
        return EVIDENCE_REJECT

    # 2. Hard floor: not enough sample, or Wilson LB doesn't beat chance.
    if n < MIN_N_FOR_ROBUST or wr_lb < MIN_WR_LB_NOT_TOO_WEAK:
        # Within this bracket, mark improving if the trajectory looks OK.
        if (MIN_N_FOR_IMPROVING <= n < MIN_N_FOR_ROBUST
                and wr_mean >= MIN_MEAN_WR_FOR_IMPROVING
                and wr_lb >= MIN_WR_LB_NOT_TOO_WEAK):
            return EVIDENCE_IMPROVING
        return EVIDENCE_TOO_WEAK

    # n ≥ 50 AND Wilson WR LB ≥ 0.40 from here on.

    # 3. Degradation check (n ≥ 40 by construction here, n ≥ 50 actually).
    if degrading_flag:
        return EVIDENCE_DEGRADING

    # 4. Robust candidate.
    if pf_lb >= MIN_PF_LB_FOR_ROBUST and exp_lb > MIN_EXP_LB_FOR_ROBUST:
        return EVIDENCE_ROBUST_CANDIDATE

    return EVIDENCE_TOO_WEAK


def classify_strategy_evidence(
    ledger: Sequence[dict],
    strategy_name: str,
    *,
    bootstrap_n: int = BOOTSTRAP_RESAMPLES,
) -> str:
    """Convenience wrapper — returns just the status string.

    Used by callers that don't need the full numeric summary.
    """
    summary = compute_strategy_evidence_bounds(
        strategy_name, ledger, bootstrap_n=bootstrap_n)
    return summary.get("status", EVIDENCE_TOO_WEAK)


__all__ = [
    # statuses
    "EVIDENCE_TOO_WEAK", "EVIDENCE_IMPROVING", "EVIDENCE_ROBUST_CANDIDATE",
    "EVIDENCE_DEGRADING", "EVIDENCE_REJECT", "EVIDENCE_STATUSES",
    # thresholds (exported for test introspection)
    "MIN_N_FOR_ROBUST", "MIN_N_FOR_IMPROVING",
    "MIN_WR_LB_NOT_TOO_WEAK", "MIN_MEAN_WR_FOR_IMPROVING",
    "MIN_PF_LB_FOR_ROBUST", "MIN_EXP_LB_FOR_ROBUST",
    "MIN_PF_MEAN_FOR_REJECT", "MAX_PF_LB_FOR_REJECT",
    "WILSON_Z", "BOOTSTRAP_RESAMPLES", "BOOTSTRAP_LOWER_PCT",
    "WORST_WINDOW", "MIN_N_FOR_DEGRADATION",
    # API
    "wilson_lower_bound", "compute_strategy_evidence_bounds",
    "classify_strategy_evidence",
]
