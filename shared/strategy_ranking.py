"""v3.19.0 (2026-06-04) — Strategy Ranking (ETAP 5).

WHY
---
The system runs many strategies in parallel on paper. Operator needs a
deterministic, evidence-based ordering — without ever raising risk or
auto-promoting anything. The ranking is purely advisory: better order =
better selection of what to observe / propose for review. It does NOT
change risk limits, position sizes, leverage, or gate flags.

CONTRACT
--------
- rank_strategies(paper_metrics_per_strategy=...) returns a deterministic
  list[dict] ordered worst-to-best by composite score. Each dict carries
  rank, strategy, score in [0,1], status, and a per-component breakdown.

- write_ranking_reports(ranked, ...) writes
  `docs/strategy_ranking_LATEST.md` + `.json` to disk. Returns the
  paths written.

- Statuses (closed enum):
    TOP_OBSERVE             — best evidence, healthy across all components
    CONTINUE_OBSERVE        — solid; nothing flashy
    NEEDS_MORE_DATA         — too thin to rank meaningfully
    REDUCE_PRIORITY         — recent degradation or weak comp
    DISABLE_CANDIDATE       — strong negative signal
    EDGE_REVIEW_CANDIDATE   — best combined evidence; humanly worth reviewing

DEFENSIVE WEIGHTS
-----------------
All components are normalized to [0,1]. Bad metrics LOWER rank — they
never raise it. Risk violations or audit incompleteness pin the
strategy to last rank (score=0.0).

NEVER mutates state.json.
NEVER sets EDGE_GATE_ENABLED.
NEVER auto-trades anything.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ─── Closed status enum ──────────────────────────────────────────────────────

TOP_OBSERVE           = "TOP_OBSERVE"
CONTINUE_OBSERVE      = "CONTINUE_OBSERVE"
NEEDS_MORE_DATA       = "NEEDS_MORE_DATA"
REDUCE_PRIORITY       = "REDUCE_PRIORITY"
DISABLE_CANDIDATE     = "DISABLE_CANDIDATE"
EDGE_REVIEW_CANDIDATE = "EDGE_REVIEW_CANDIDATE"

ALL_STATUSES = frozenset({
    TOP_OBSERVE, CONTINUE_OBSERVE, NEEDS_MORE_DATA,
    REDUCE_PRIORITY, DISABLE_CANDIDATE, EDGE_REVIEW_CANDIDATE,
})


# ─── Component weights (sum normalized later) ────────────────────────────────

# All weights are positive; bad metric values map to LOW component scores.
# Hard violations (risk / audit_incomplete) pin score to 0.0 regardless.
COMPONENT_WEIGHTS: dict[str, float] = {
    "n_closed":                    0.05,
    "profit_factor":               0.18,
    "expectancy":                  0.12,
    "win_rate":                    0.10,
    "max_drawdown":                0.10,    # lower DD ⇒ higher comp
    "slippage_adjusted_pf":        0.08,
    "fee_adjusted_expectancy":     0.07,
    "confidence_calibration":      0.10,
    "regime_stability":            0.10,
    "instrument_concentration":    0.05,    # low concentration ⇒ higher
    "recent_degradation_penalty":  0.05,    # no degradation ⇒ higher
}
# risk_violations + audit_completeness are not part of the weighted sum.
# They are hard gates: any failure → score=0.0 last rank.


# ─── Status thresholds ───────────────────────────────────────────────────────

EDGE_REVIEW_SCORE_MIN     = 0.78
TOP_OBSERVE_SCORE_MIN     = 0.65
CONTINUE_OBSERVE_SCORE_MIN = 0.45
REDUCE_PRIORITY_SCORE_MAX = 0.25
NEEDS_MORE_DATA_MIN_N     = 10


# ─── Helpers ────────────────────────────────────────────────────────────────

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


def _clip01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


# ─── Component computations (each returns [0,1]) ────────────────────────────

def _comp_n_closed(metrics: Mapping[str, Any]) -> float:
    """Sample size — capped at 100. n=10→0.1, n=50→0.5, n>=100→1.0."""
    n = _safe_int(metrics.get("n_closed"))
    if n <= 0:
        return 0.0
    return _clip01(n / 100.0)


def _comp_profit_factor(metrics: Mapping[str, Any]) -> float:
    """PF≤0.5→0, PF=1.0→0.45, PF>=1.5→1.0."""
    pf = _safe_float(metrics.get("profit_factor"))
    if pf <= 0.5:
        return 0.0
    if pf >= 1.5:
        return 1.0
    # Linear between PF=0.5 (0.0) and PF=1.5 (1.0)
    return _clip01((pf - 0.5) / 1.0)


def _comp_expectancy(metrics: Mapping[str, Any]) -> float:
    """Expectancy positive → reward; negative → 0."""
    exp = _safe_float(metrics.get("expectancy"))
    if exp <= 0:
        return 0.0
    # Soft cap: $50 expectancy per trade ⇒ 1.0
    return _clip01(exp / 50.0)


def _comp_win_rate(metrics: Mapping[str, Any]) -> float:
    """WR<30%→0, WR=50%→0.4, WR>=70%→1.0."""
    wr = _safe_float(metrics.get("win_rate"))
    if wr <= 0.30:
        return 0.0
    if wr >= 0.70:
        return 1.0
    # Linear 0.30→0.0, 0.70→1.0
    return _clip01((wr - 0.30) / 0.40)


def _comp_max_drawdown(metrics: Mapping[str, Any]) -> float:
    """Lower drawdown is better. DD<=10%→1.0, DD>=40%→0.0."""
    dd = _safe_float(metrics.get("max_drawdown"))
    if dd <= 0.10:
        return 1.0
    if dd >= 0.40:
        return 0.0
    return _clip01(1.0 - (dd - 0.10) / 0.30)


def _comp_slippage_adjusted_pf(metrics: Mapping[str, Any]) -> float:
    """Use slippage_adjusted_pf if present, else profit_factor as proxy."""
    pf = metrics.get("slippage_adjusted_pf")
    if pf is None:
        pf = metrics.get("profit_factor")
    pf = _safe_float(pf)
    if pf <= 0.5:
        return 0.0
    if pf >= 1.5:
        return 1.0
    return _clip01((pf - 0.5) / 1.0)


def _comp_fee_adjusted_expectancy(metrics: Mapping[str, Any]) -> float:
    """Use fee_adjusted_expectancy if present, else expectancy."""
    exp = metrics.get("fee_adjusted_expectancy")
    if exp is None:
        exp = metrics.get("expectancy")
    exp = _safe_float(exp)
    if exp <= 0:
        return 0.0
    return _clip01(exp / 50.0)


def _comp_confidence_calibration(metrics: Mapping[str, Any],
                                 calibration_scores: Mapping[str, Any] | None,
                                 strategy: str) -> float:
    """Higher = better calibration. Reads from calibration_scores[strategy]
    or metrics['confidence_calibration']. Range mapping:
      score <= 0.3 → 0.0
      score >= 0.8 → 1.0
    """
    raw = None
    if isinstance(calibration_scores, Mapping):
        raw = calibration_scores.get(strategy)
    if raw is None:
        raw = metrics.get("confidence_calibration")
    score = _safe_float(raw, default=0.5)  # neutral when unknown
    if score <= 0.30:
        return 0.0
    if score >= 0.80:
        return 1.0
    return _clip01((score - 0.30) / 0.50)


def _comp_regime_stability(metrics: Mapping[str, Any],
                           regime_stability: Mapping[str, Any] | None,
                           strategy: str) -> float:
    """Multi-regime evidence: ≥3 positive regimes ⇒ 1.0; 2 ⇒ 0.6; 1 ⇒ 0.3;
    0 ⇒ 0.0. Falls back to counting per_regime block in metrics.
    """
    n_regimes_pos = None
    if isinstance(regime_stability, Mapping):
        rs = regime_stability.get(strategy)
        if isinstance(rs, Mapping):
            n_regimes_pos = rs.get("positive_regimes")
        elif rs is not None:
            try:
                n_regimes_pos = int(rs)
            except (TypeError, ValueError):
                n_regimes_pos = None
    if n_regimes_pos is None:
        # Count per_regime block from metrics
        per_regime = metrics.get("per_regime")
        if isinstance(per_regime, Mapping):
            n_regimes_pos = 0
            for label, sub in per_regime.items():
                if label in (None, "", "unknown"):
                    continue
                if not isinstance(sub, Mapping):
                    continue
                n = _safe_int(sub.get("n_closed"))
                net = _safe_float(sub.get("net_pnl_after_fees_slippage"))
                exp = _safe_float(sub.get("expectancy"))
                if n >= 5 and (net > 0 or exp > 0):
                    n_regimes_pos += 1
        else:
            n_regimes_pos = 0
    n_regimes_pos = _safe_int(n_regimes_pos)
    if n_regimes_pos <= 0:
        return 0.0
    if n_regimes_pos >= 3:
        return 1.0
    if n_regimes_pos == 2:
        return 0.6
    return 0.3


def _comp_instrument_concentration(metrics: Mapping[str, Any]) -> float:
    """Lower concentration is better.

    Reads either:
      - metrics["instrument_concentration"] (float 0..1, share of top symbol)
      - metrics["per_symbol"] dict — compute top-symbol share automatically.

    Single-symbol strategies (1 symbol or top share > 80%) are penalised hard.
    """
    raw_share = metrics.get("instrument_concentration")
    if raw_share is None:
        per_sym = metrics.get("per_symbol")
        if isinstance(per_sym, Mapping) and per_sym:
            totals = []
            for _, sub in per_sym.items():
                if isinstance(sub, Mapping):
                    totals.append(_safe_int(sub.get("n_closed")))
            tot = sum(totals)
            if tot > 0:
                raw_share = max(totals) / float(tot)
    share = _safe_float(raw_share, default=1.0)
    if share >= 0.80:
        return 0.0
    if share <= 0.30:
        return 1.0
    return _clip01(1.0 - (share - 0.30) / 0.50)


def _comp_recent_degradation_penalty(metrics: Mapping[str, Any]) -> float:
    """Reward no-degradation. Reads metrics['last_20_win_rate']."""
    n = _safe_int(metrics.get("n_closed"))
    if n < 20:
        return 0.6  # neutral when too thin to call degradation
    last20 = _safe_float(metrics.get("last_20_win_rate"))
    if last20 <= 0.20:
        return 0.0
    if last20 >= 0.50:
        return 1.0
    return _clip01((last20 - 0.20) / 0.30)


# ─── Status mapping ──────────────────────────────────────────────────────────

def _status_from_score(score: float, n_closed: int,
                       per_strategy_paper_metrics: Mapping[str, Any] | None
                       = None) -> str:
    if n_closed < NEEDS_MORE_DATA_MIN_N:
        return NEEDS_MORE_DATA
    if score >= EDGE_REVIEW_SCORE_MIN:
        return EDGE_REVIEW_CANDIDATE
    if score >= TOP_OBSERVE_SCORE_MIN:
        return TOP_OBSERVE
    if score >= CONTINUE_OBSERVE_SCORE_MIN:
        return CONTINUE_OBSERVE
    if score <= 0.10:
        return DISABLE_CANDIDATE
    if score <= REDUCE_PRIORITY_SCORE_MAX:
        return REDUCE_PRIORITY
    return CONTINUE_OBSERVE


# ─── Compose per-strategy score ──────────────────────────────────────────────

def _compose_score(strategy: str,
                   metrics: Mapping[str, Any],
                   calibration_scores: Mapping[str, Any] | None,
                   regime_stability: Mapping[str, Any] | None,
                   ) -> tuple[float, dict, dict]:
    """Return (score, component_breakdown, hard_violations).

    hard_violations contains {"risk_violations": int, "audit_incomplete": bool}.
    Score is pinned to 0.0 if any hard violation is present.
    """
    components: dict[str, float] = {
        "n_closed":                    _comp_n_closed(metrics),
        "profit_factor":               _comp_profit_factor(metrics),
        "expectancy":                  _comp_expectancy(metrics),
        "win_rate":                    _comp_win_rate(metrics),
        "max_drawdown":                _comp_max_drawdown(metrics),
        "slippage_adjusted_pf":        _comp_slippage_adjusted_pf(metrics),
        "fee_adjusted_expectancy":     _comp_fee_adjusted_expectancy(metrics),
        "confidence_calibration":      _comp_confidence_calibration(
                                            metrics, calibration_scores, strategy),
        "regime_stability":            _comp_regime_stability(
                                            metrics, regime_stability, strategy),
        "instrument_concentration":    _comp_instrument_concentration(metrics),
        "recent_degradation_penalty":  _comp_recent_degradation_penalty(metrics),
    }

    # Hard gates
    risk_violations = _safe_int(metrics.get("risk_violations"))
    audit_incomplete = bool(metrics.get("audit_incomplete"))
    if risk_violations > 0 or audit_incomplete:
        return 0.0, components, {
            "risk_violations":  risk_violations,
            "audit_incomplete": audit_incomplete,
        }

    # Weighted sum, normalized by total weight.
    total_w = sum(COMPONENT_WEIGHTS.values())
    if total_w <= 0:
        score = 0.0
    else:
        score = sum(components[k] * w for k, w in COMPONENT_WEIGHTS.items()) / total_w
    score = _clip01(round(score, 6))
    return score, components, {
        "risk_violations":  0,
        "audit_incomplete": False,
    }


# ─── Audit emission ──────────────────────────────────────────────────────────

def _emit_ranking_audit(strategy: str, status: str, score: float,
                        rationale: str, components: Mapping[str, float]) -> None:
    """Emit a non-blocking JSONL audit row. Fail-soft."""
    try:
        from shared.audit import write_audit_event  # type: ignore
        from shared.autonomy import make_decision    # type: ignore
    except Exception:
        try:
            from audit import write_audit_event       # type: ignore
            from autonomy import make_decision        # type: ignore
        except Exception:
            return
    try:
        decision_type = "PAUSE_STRATEGY" if status in (
            DISABLE_CANDIDATE, REDUCE_PRIORITY) else "RESUME_STRATEGY"
        d = make_decision(
            decision_type=decision_type,
            decision=status,
            reason=f"learning_recommendation (rank): {rationale}",
            actor="strategy-ranking",
            strategy=strategy,
            risk_metrics={
                "score":                  round(float(score), 6),
                **{f"comp_{k}": round(float(v), 6)
                   for k, v in components.items()},
            },
            reversible=True,
        )
        write_audit_event(d, kind="trading")
    except Exception:
        return


# ─── Public API ──────────────────────────────────────────────────────────────

def rank_strategies(*,
                    paper_metrics_per_strategy: Mapping[str, Mapping[str, Any]]
                        | None = None,
                    calibration_scores: Mapping[str, Any] | None = None,
                    regime_stability: Mapping[str, Any] | None = None,
                    emit_audit: bool = True) -> list[dict]:
    """Return a deterministic ordered list of ranking dicts.

    Order is by (score DESC, strategy name ASC) so same input → same order.
    Returns [] for None / empty input.
    """
    if paper_metrics_per_strategy is None:
        return []
    if not isinstance(paper_metrics_per_strategy, Mapping):
        return []
    if not paper_metrics_per_strategy:
        return []

    rows: list[dict] = []
    for strategy, metrics in paper_metrics_per_strategy.items():
        if not isinstance(metrics, Mapping):
            continue
        try:
            score, components, violations = _compose_score(
                strategy, metrics, calibration_scores, regime_stability)
        except Exception:
            score, components, violations = 0.0, {}, {
                "risk_violations": 1,
                "audit_incomplete": True,
            }
        n_closed = _safe_int(metrics.get("n_closed"))
        if violations.get("risk_violations") or violations.get("audit_incomplete"):
            status = DISABLE_CANDIDATE
        else:
            status = _status_from_score(score, n_closed, metrics)
        rationale = (f"n={n_closed} WR={_safe_float(metrics.get('win_rate'))} "
                     f"PF={_safe_float(metrics.get('profit_factor'))} "
                     f"score={score:.4f}")
        if emit_audit:
            _emit_ranking_audit(strategy, status, score, rationale, components)
        rows.append({
            "strategy":   strategy,
            "score":      round(float(score), 6),
            "status":     status,
            "components": {k: round(float(v), 6) for k, v in components.items()},
            "violations": violations,
            "n_closed":   n_closed,
        })

    # Deterministic order: by score DESC, then strategy ASC.
    rows.sort(key=lambda r: (-r["score"], r["strategy"]))
    for idx, r in enumerate(rows, start=1):
        r["rank"] = idx
    return rows


def write_ranking_reports(ranked: list[dict],
                           *,
                           out_md_path: str | None = None,
                           out_json_path: str | None = None
                           ) -> tuple[str, str]:
    """Write Markdown + JSON ranking reports to disk. Returns paths."""
    if not isinstance(ranked, list):
        ranked = []
    out_md = Path(out_md_path) if out_md_path else (
        _REPO_ROOT / "docs" / "strategy_ranking_LATEST.md")
    out_json = Path(out_json_path) if out_json_path else (
        _REPO_ROOT / "docs" / "strategy_ranking_LATEST.json")

    # Markdown
    lines: list[str] = []
    lines.append("# Strategy Ranking (paper trading)")
    lines.append("")
    lines.append(
        "*Advisory only. Paper trading evidence. Never auto-promotes; "
        "never raises risk; never sets EDGE_GATE_ENABLED.*"
    )
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append("")
    lines.append(
        "| Rank | Strategy | Score | Status | n_closed |"
    )
    lines.append(
        "|---:|---|---:|---|---:|"
    )
    for r in ranked:
        lines.append(
            f"| {r.get('rank','?')} | {r.get('strategy','?')} | "
            f"{r.get('score',0.0):.4f} | {r.get('status','?')} | "
            f"{r.get('n_closed',0)} |"
        )
    lines.append("")
    lines.append("## Components (per strategy, [0..1])")
    lines.append("")
    for r in ranked:
        lines.append(f"### {r.get('strategy','?')}  ({r.get('status','?')}, "
                     f"score {r.get('score',0.0):.4f})")
        comps = r.get("components") or {}
        for k in sorted(comps.keys()):
            lines.append(f"- {k}: {comps[k]:.4f}")
        if r.get("violations") and (r["violations"].get("risk_violations")
                                    or r["violations"].get("audit_incomplete")):
            lines.append(f"- HARD VIOLATIONS: {json.dumps(r['violations'])}")
        lines.append("")
    md = "\n".join(lines) + "\n"

    try:
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(md, encoding="utf-8")
    except OSError:
        pass

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "paper_only":   True,
        "ranked":       ranked,
    }
    try:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(payload, indent=2, sort_keys=True),
                            encoding="utf-8")
    except OSError:
        pass

    return str(out_md), str(out_json)


__all__ = [
    # Statuses
    "TOP_OBSERVE", "CONTINUE_OBSERVE", "NEEDS_MORE_DATA",
    "REDUCE_PRIORITY", "DISABLE_CANDIDATE", "EDGE_REVIEW_CANDIDATE",
    "ALL_STATUSES",
    # Thresholds
    "COMPONENT_WEIGHTS",
    "EDGE_REVIEW_SCORE_MIN", "TOP_OBSERVE_SCORE_MIN",
    "CONTINUE_OBSERVE_SCORE_MIN", "REDUCE_PRIORITY_SCORE_MAX",
    "NEEDS_MORE_DATA_MIN_N",
    # API
    "rank_strategies", "write_ranking_reports",
]
