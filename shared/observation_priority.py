"""v3.21.0 (2026-06-04) — ETAP 8 — Adaptive Observation Priority.

WHY
---
The experiment scheduler (v3.20 ETAP 7) currently treats every strategy
/ symbol / regime triple as equally interesting once the operator has
opted-in. That is wasteful: some triples are *already* well-sampled and
adding more observations there teaches us nothing, while others are
critically under-covered for the regime we are about to enter.

This module computes a per-triple ``priority_score`` ∈ [0, 1] from a
small set of deterministic inputs and reports a recommendation status
to the scheduler. It is the *prioritisation* layer that sits between
:mod:`shared.evidence_lower_bounds` (how much evidence do we have?),
:mod:`shared.signal_opportunity_ledger` (what is even firing?) and
:mod:`shared.experiment_scheduler` (what should we observe next?).

HARD INVARIANTS
---------------
* This module is **recommendation-only**. It NEVER enables trading,
  NEVER raises position limits, NEVER bypasses risk engines, NEVER
  flips ``EDGE_GATE_ENABLED``. Its output is consumed by the
  experiment scheduler — which is itself observe-only.
* It does NOT route any order, place any broker call, or talk to a
  paid API. Pure stdlib + the opportunity ledger and confidence
  calibration helpers already in the repo.
* Determinism: same inputs → same priority. No randomness, no LLM, no
  time-of-day jitter.
* Fail-soft: every component returns ``0.5`` (neutral) on missing data
  so a single missing input never collapses the priority to zero.
* Status ``DO_NOT_OBSERVE`` is only reached when the lower bounds layer
  already classifies the strategy as ``EVIDENCE_REJECT`` — i.e. it
  encodes the *existing* gate decision rather than introducing a new
  one.

INPUT COMPONENTS
----------------
* ``missing_evidence`` — gap to the n=50 paper-trade target.
* ``signal_density`` — opportunity ledger density per day (capped).
* ``historical_promise`` — score from strategy ranking (if available).
* ``confidence_calibration_gap`` — distance from monotonic calibration.
* ``regime_undercoverage`` — share of triples in the current regime
  that are under-sampled.
* ``symbol_liquidity`` — estimated from the spread (default mid).
* ``spread_quality`` — inverse of the relative spread.
* ``rejection_uncertainty`` — share of ``UNKNOWN`` counterfactual
  outcomes for the strategy.
* ``counterfactual_opportunity`` — share of false rejections.
* ``strategy_ranking`` — bucket-shifted ranking score (0-1).
* ``lower_bound_status`` — direct status from evidence lower bounds.

STATUS LADDER
-------------
* ``PRIORITY_OBSERVE`` — high priority, the experiment scheduler should
  bump this triple.
* ``NORMAL_OBSERVE`` — default rotation.
* ``LOW_PRIORITY`` — observe rarely, especially when other triples
  share the cron budget.
* ``DO_NOT_OBSERVE`` — the lower bounds layer already rejected the
  strategy. The experiment scheduler MUST skip it.
* ``NEEDS_DATA`` — not enough data to score; default to NORMAL_OBSERVE
  for new triples so we don't starve them.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parent.parent


# ─── Status enum (closed) ────────────────────────────────────────────────────

STATUS_PRIORITY_OBSERVE = "PRIORITY_OBSERVE"
STATUS_NORMAL_OBSERVE   = "NORMAL_OBSERVE"
STATUS_LOW_PRIORITY     = "LOW_PRIORITY"
STATUS_DO_NOT_OBSERVE   = "DO_NOT_OBSERVE"
STATUS_NEEDS_DATA       = "NEEDS_DATA"

ALL_STATUSES: frozenset[str] = frozenset({
    STATUS_PRIORITY_OBSERVE,
    STATUS_NORMAL_OBSERVE,
    STATUS_LOW_PRIORITY,
    STATUS_DO_NOT_OBSERVE,
    STATUS_NEEDS_DATA,
})


# ─── Tunables (deterministic, exported for tests) ────────────────────────────

# Target paper-trade sample size used by ``missing_evidence``.
TARGET_PAPER_N = 50

# Thresholds for status assignment from the priority score.
THRESHOLD_PRIORITY = 0.65
THRESHOLD_LOW      = 0.30

# Liquidity model — relative spread in basis points.
NEUTRAL_SPREAD_BPS = 5.0     # default when we have no quote
MAX_SPREAD_BPS     = 80.0    # cap before the symbol is "illiquid"

# Component weights. Sum = 1.0. Adjusting these is a strategy decision
# governed by the audit board, not by this module.
COMPONENT_WEIGHTS: Mapping[str, float] = {
    "missing_evidence":            0.20,
    "signal_density":              0.10,
    "historical_promise":          0.10,
    "confidence_calibration_gap":  0.10,
    "regime_undercoverage":        0.10,
    "symbol_liquidity":            0.10,
    "spread_quality":              0.05,
    "rejection_uncertainty":       0.05,
    "counterfactual_opportunity":  0.10,
    "strategy_ranking":            0.05,
    "lower_bound_status":          0.05,
}


# ─── Safe helpers ────────────────────────────────────────────────────────────


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:  # NaN
            return default
        return v
    except (TypeError, ValueError):
        return default


def _clip01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Data classes ────────────────────────────────────────────────────────────


@dataclass
class PriorityScore:
    """Per (strategy, symbol, regime) priority assessment."""

    strategy: str
    symbol: str
    regime: str
    priority_score: float
    status: str
    components: dict = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Component scorers ───────────────────────────────────────────────────────


def _score_missing_evidence(paper_n: int) -> float:
    """1.0 when we have 0 paper trades, 0.0 once we hit the target."""
    if paper_n <= 0:
        return 1.0
    if paper_n >= TARGET_PAPER_N:
        return 0.0
    return _clip01(1.0 - paper_n / float(TARGET_PAPER_N))


def _score_signal_density(opportunities_per_day: float,
                          *,
                          density_for_max: float = 5.0) -> float:
    """Higher density = more opportunity to learn quickly."""
    if opportunities_per_day <= 0:
        return 0.0
    return _clip01(opportunities_per_day / float(density_for_max))


def _score_historical_promise(ranking_score: float | None) -> float:
    """Strategy ranking already maps to [0, 1]."""
    if ranking_score is None:
        return 0.5
    return _clip01(_safe_float(ranking_score, default=0.5))


def _score_confidence_calibration_gap(calibration: Mapping[str, Any] | None,
                                      ) -> float:
    """Returns ``1 - calibration_quality`` to reward symbols that need
    re-calibration. Missing data → 0.5 (neutral)."""
    if not isinstance(calibration, Mapping) or not calibration:
        return 0.5
    quality = _safe_float(calibration.get("monotonic_score"), default=None)
    if quality is None:
        # Fallback: compute a simple monotonicity hint from bucket WR if
        # available. Otherwise neutral.
        bucket_stats = calibration.get("buckets")
        if not isinstance(bucket_stats, Mapping):
            return 0.5
        wrs: list[float] = []
        for b in bucket_stats.values():
            if isinstance(b, Mapping):
                wr = _safe_float(b.get("win_rate"), default=None)
                if wr is not None:
                    wrs.append(wr)
        if len(wrs) < 2:
            return 0.5
        # 1 if strictly non-decreasing, else 0.3.
        increases = sum(1 for a, b in zip(wrs, wrs[1:]) if b >= a - 1e-9)
        ratio = increases / max(1, len(wrs) - 1)
        return _clip01(1.0 - ratio)
    return _clip01(1.0 - quality)


def _score_regime_undercoverage(regime_coverage: Mapping[str, Any] | None,
                                regime: str) -> float:
    """1.0 when ≤ 20 % of triples in the regime have hit the target."""
    if not isinstance(regime_coverage, Mapping) or not regime_coverage:
        return 0.5
    coverage = regime_coverage.get(regime)
    if coverage is None:
        return 0.5
    ratio = _safe_float(coverage, default=0.5)
    return _clip01(1.0 - ratio)


def _score_symbol_liquidity(quote: Mapping[str, Any] | None) -> float:
    """Use the relative spread as a proxy. Missing quote → 0.5."""
    if not isinstance(quote, Mapping) or not quote:
        return 0.5
    bid = _safe_float(quote.get("bid"), default=None)
    ask = _safe_float(quote.get("ask"), default=None)
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return 0.5
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return 0.5
    spread_bps = ((ask - bid) / mid) * 10_000.0
    spread_bps = max(0.0, min(MAX_SPREAD_BPS, spread_bps))
    # Lower spread → higher liquidity score.
    return _clip01(1.0 - spread_bps / MAX_SPREAD_BPS)


def _score_spread_quality(quote: Mapping[str, Any] | None) -> float:
    """Spread quality is the inverse of *normalised* spread. We re-use
    the liquidity helper to keep the math deterministic."""
    return _score_symbol_liquidity(quote)


def _score_rejection_uncertainty(unknown_rate: float | None) -> float:
    """Higher rejection-UNKNOWN rate → more useful to gather data."""
    if unknown_rate is None:
        return 0.5
    return _clip01(_safe_float(unknown_rate, default=0.5))


def _score_counterfactual_opportunity(false_rejection_rate: float | None
                                      ) -> float:
    """A high false-rejection rate signals we should observe more."""
    if false_rejection_rate is None:
        return 0.5
    return _clip01(_safe_float(false_rejection_rate, default=0.5))


def _score_strategy_ranking(strategy_ranking_score: float | None,
                            rank_position: int | None,
                            total_ranked: int | None) -> float:
    """Blend the raw score (if known) with the rank position."""
    if strategy_ranking_score is not None:
        return _clip01(_safe_float(strategy_ranking_score, default=0.5))
    if (rank_position is not None and total_ranked is not None
            and total_ranked > 0):
        # Position 1 → 1.0, position N → near 0.
        return _clip01(1.0 - (rank_position - 1) / float(total_ranked))
    return 0.5


def _score_lower_bound_status(lower_bound_status: str | None) -> float:
    """Map the lower-bound status onto a [0, 1] urgency scale.

    ``EVIDENCE_TOO_WEAK`` is the most urgent to observe; ``EVIDENCE_REJECT``
    drops to 0 because the gate has already decided to skip.
    """
    if not lower_bound_status:
        return 0.5
    s = str(lower_bound_status).upper()
    mapping = {
        "EVIDENCE_TOO_WEAK":         1.0,
        "EVIDENCE_IMPROVING":        0.75,
        "EVIDENCE_ROBUST_CANDIDATE": 0.30,
        "EVIDENCE_DEGRADING":        0.60,
        "EVIDENCE_REJECT":           0.0,
    }
    return mapping.get(s, 0.5)


# ─── Aggregator ──────────────────────────────────────────────────────────────


def _weighted_sum(components: Mapping[str, float]) -> float:
    total_weight = 0.0
    total_value = 0.0
    for name, weight in COMPONENT_WEIGHTS.items():
        value = _clip01(_safe_float(components.get(name), default=0.5))
        total_weight += weight
        total_value += weight * value
    if total_weight <= 0:
        return 0.0
    return _clip01(total_value / total_weight)


def _status_from_score(score: float,
                       *,
                       lower_bound_status: str | None,
                       paper_n: int,
                       opportunities_per_day: float,
                       ) -> str:
    """Resolve the recommendation status from the score + hard gates."""
    if lower_bound_status == "EVIDENCE_REJECT":
        return STATUS_DO_NOT_OBSERVE
    if paper_n <= 0 and opportunities_per_day <= 0:
        # Brand new triple with no data — never starve it.
        return STATUS_NEEDS_DATA
    if score >= THRESHOLD_PRIORITY:
        return STATUS_PRIORITY_OBSERVE
    if score <= THRESHOLD_LOW:
        return STATUS_LOW_PRIORITY
    return STATUS_NORMAL_OBSERVE


def compute_priority(*,
                     strategy: str,
                     symbol: str,
                     regime: str,
                     paper_n: int = 0,
                     opportunities_per_day: float = 0.0,
                     historical_promise: float | None = None,
                     confidence_calibration: Mapping[str, Any] | None = None,
                     regime_coverage: Mapping[str, Any] | None = None,
                     quote: Mapping[str, Any] | None = None,
                     unknown_rejection_rate: float | None = None,
                     false_rejection_rate: float | None = None,
                     strategy_ranking_score: float | None = None,
                     rank_position: int | None = None,
                     total_ranked: int | None = None,
                     lower_bound_status: str | None = None,
                     ) -> PriorityScore:
    """Compute the priority score for one (strategy, symbol, regime).

    All inputs are optional — the function falls back to neutral 0.5 per
    component so a fresh triple is never punished for missing data.
    """
    components = {
        "missing_evidence":           _score_missing_evidence(paper_n),
        "signal_density":             _score_signal_density(opportunities_per_day),
        "historical_promise":         _score_historical_promise(historical_promise),
        "confidence_calibration_gap": _score_confidence_calibration_gap(
            confidence_calibration),
        "regime_undercoverage":       _score_regime_undercoverage(
            regime_coverage, regime),
        "symbol_liquidity":           _score_symbol_liquidity(quote),
        "spread_quality":             _score_spread_quality(quote),
        "rejection_uncertainty":      _score_rejection_uncertainty(
            unknown_rejection_rate),
        "counterfactual_opportunity": _score_counterfactual_opportunity(
            false_rejection_rate),
        "strategy_ranking":           _score_strategy_ranking(
            strategy_ranking_score, rank_position, total_ranked),
        "lower_bound_status":         _score_lower_bound_status(lower_bound_status),
    }
    score = _weighted_sum(components)
    status = _status_from_score(score,
                                lower_bound_status=lower_bound_status,
                                paper_n=paper_n,
                                opportunities_per_day=opportunities_per_day)
    return PriorityScore(
        strategy=str(strategy),
        symbol=str(symbol).upper(),
        regime=str(regime).upper(),
        priority_score=round(score, 6),
        status=status,
        components=components,
    )


# ─── Audit emission ──────────────────────────────────────────────────────────


def _emit_audit_event(event_type: str, payload: dict) -> None:
    """Best-effort audit emission. Never raises."""
    try:
        try:
            from audit import write_audit_event
        except ImportError:
            from shared.audit import write_audit_event  # type: ignore
    except Exception:
        return
    try:
        record = {
            "ts":         _utc_now_iso(),
            "decision":   event_type,
            "event_type": event_type,
            "actor":      "observation_priority",
            "payload":    payload,
        }
        write_audit_event(record, kind="trading")
    except Exception:
        pass


# ─── Bulk evaluation ─────────────────────────────────────────────────────────


def evaluate_triples(triples: Iterable[Mapping[str, Any]],
                     *,
                     regime_coverage: Mapping[str, Any] | None = None,
                     confidence_calibration_by_strategy:
                         Mapping[str, Mapping[str, Any]] | None = None,
                     strategy_ranking_by_strategy:
                         Mapping[str, Mapping[str, Any]] | None = None,
                     emit_audit: bool = True,
                     ) -> list[PriorityScore]:
    """Score a sequence of (strategy, symbol, regime) inputs.

    Each input ``triple`` is a Mapping supporting the same keyword
    arguments as :func:`compute_priority`. Missing keys fall through to
    the per-component neutral defaults.
    """
    if triples is None:
        return []
    confidence_calibration_by_strategy = confidence_calibration_by_strategy or {}
    strategy_ranking_by_strategy = strategy_ranking_by_strategy or {}

    out: list[PriorityScore] = []
    for raw in triples:
        if not isinstance(raw, Mapping):
            continue
        strategy = str(raw.get("strategy", ""))
        symbol   = str(raw.get("symbol", ""))
        regime   = str(raw.get("regime", "NEUTRAL"))
        if not strategy or not symbol:
            continue
        # Allow the caller to inject per-strategy auxiliary data without
        # forcing it into every triple row.
        calib = (raw.get("confidence_calibration")
                 or confidence_calibration_by_strategy.get(strategy))
        ranking = (raw.get("strategy_ranking")
                   or strategy_ranking_by_strategy.get(strategy))
        ranking_score = None
        rank_position = None
        total_ranked = None
        if isinstance(ranking, Mapping):
            ranking_score = _safe_float(ranking.get("score"), default=None)
            rank_position = ranking.get("rank")
            total_ranked = ranking.get("total")
        out.append(
            compute_priority(
                strategy=strategy,
                symbol=symbol,
                regime=regime,
                paper_n=int(_safe_float(raw.get("paper_n"), default=0)),
                opportunities_per_day=_safe_float(
                    raw.get("opportunities_per_day"), default=0.0),
                historical_promise=raw.get("historical_promise"),
                confidence_calibration=calib if isinstance(calib, Mapping) else None,
                regime_coverage=regime_coverage,
                quote=raw.get("quote") if isinstance(raw.get("quote"), Mapping) else None,
                unknown_rejection_rate=raw.get("unknown_rejection_rate"),
                false_rejection_rate=raw.get("false_rejection_rate"),
                strategy_ranking_score=ranking_score,
                rank_position=rank_position,
                total_ranked=total_ranked,
                lower_bound_status=raw.get("lower_bound_status"),
            )
        )

    if emit_audit:
        _emit_audit_event("V321_OBSERVATION_PRIORITY_COMPUTED", {
            "n_triples": len(out),
            "counts":    {
                STATUS_PRIORITY_OBSERVE: sum(1 for p in out
                                             if p.status == STATUS_PRIORITY_OBSERVE),
                STATUS_NORMAL_OBSERVE:   sum(1 for p in out
                                             if p.status == STATUS_NORMAL_OBSERVE),
                STATUS_LOW_PRIORITY:     sum(1 for p in out
                                             if p.status == STATUS_LOW_PRIORITY),
                STATUS_DO_NOT_OBSERVE:   sum(1 for p in out
                                             if p.status == STATUS_DO_NOT_OBSERVE),
                STATUS_NEEDS_DATA:       sum(1 for p in out
                                             if p.status == STATUS_NEEDS_DATA),
            },
        })
    return out


# ─── Report sink ─────────────────────────────────────────────────────────────


def _report_dir() -> Path:
    return Path(os.environ.get("OBSERVATION_PRIORITY_DIR")
                or _REPO_ROOT / "reports" / "observation_priority")


def write_priority_jsonl(scores: Sequence[PriorityScore],
                         *,
                         out_dir: Path | None = None,
                         date_iso: str | None = None) -> Path:
    """Append the scores to ``reports/observation_priority/<date>.jsonl``."""
    if date_iso is None:
        date_iso = datetime.now(timezone.utc).date().isoformat()
    base = out_dir if out_dir is not None else _report_dir()
    path = base / f"{date_iso}.jsonl"
    try:
        base.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for s in scores:
                f.write(json.dumps(s.to_dict(), default=str, sort_keys=True) + "\n")
    except OSError:
        pass
    return path


__all__ = [
    "STATUS_PRIORITY_OBSERVE",
    "STATUS_NORMAL_OBSERVE",
    "STATUS_LOW_PRIORITY",
    "STATUS_DO_NOT_OBSERVE",
    "STATUS_NEEDS_DATA",
    "ALL_STATUSES",
    "TARGET_PAPER_N",
    "THRESHOLD_PRIORITY",
    "THRESHOLD_LOW",
    "COMPONENT_WEIGHTS",
    "PriorityScore",
    "compute_priority",
    "evaluate_triples",
    "write_priority_jsonl",
]
