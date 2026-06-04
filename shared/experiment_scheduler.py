"""v3.20.0 (2026-06-04) — ETAP 7 — Experiment Scheduler.

WHY
---
The system observes paper trading and accumulates partial evidence
about strategies. To grow that evidence base efficiently, an
observation plan tells the operator (and the learning-loop) which
strategies / symbols / variants / rejected signals / confidence
buckets / regimes deserve more attention next.

This scheduler reads:
  - the deterministic strategy ranking (shared/strategy_ranking.py)
  - the paper-experiment opportunity ledger (best-effort, may be empty)
  - confidence calibration buckets (best-effort, may be empty)
  - evidence lower bounds (best-effort, may be empty)
  - quarantined variants (shared/strategy_variant_quarantine.py)

…and produces an observation plan. The plan ONLY tells the operator
what to look at. It NEVER changes risk, never places trades, never
flips gate flags.

CONTRACT
--------
- generate_plan(...) → dict (the plan, deterministic for fixed input).
- write_plan_to_disk(plan) → list[Path] (the persisted files).

OUTPUTS
-------
  - learning-loop/experiment_plans/experiment_plan_<date>.json
  - docs/experiment_plan_LATEST.md

PLAN SHAPE
----------
{
  "ts_iso":                       <utc ISO timestamp>,
  "plan_date":                    "YYYY-MM-DD",
  "strategies_to_observe":        [...],
  "symbols_to_observe":           [...],
  "variants_to_replay":           [...],
  "rejected_signals_to_analyze":  [...],
  "confidence_buckets_needing_data": [...],
  "underrepresented_regimes":     [...],
  "invariants":                   {SCHEDULER_NEVER_PLACES_TRADES: True, ...}
}

FREE OPERATION
--------------
Pure stdlib. No paid APIs. No network. Deterministic for fixed inputs.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


# ─── Module location bootstrap ────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ─── Invariants (asserted in tests + emitted in plan output) ─────────────────

SCHEDULER_NEVER_PLACES_TRADES = True
SCHEDULER_NEVER_RAISES_RISK   = True
SCHEDULER_NEVER_CHANGES_GATES = True

INVARIANTS: dict[str, bool] = {
    "SCHEDULER_NEVER_PLACES_TRADES": SCHEDULER_NEVER_PLACES_TRADES,
    "SCHEDULER_NEVER_RAISES_RISK":   SCHEDULER_NEVER_RAISES_RISK,
    "SCHEDULER_NEVER_CHANGES_GATES": SCHEDULER_NEVER_CHANGES_GATES,
}


# ─── Plan size caps (deterministic) ──────────────────────────────────────────

MAX_STRATEGIES_OBSERVE     = 10
MAX_SYMBOLS_OBSERVE        = 20
MAX_VARIANTS_REPLAY        = 10
MAX_REJECTED_SIGNALS       = 20
MAX_CONFIDENCE_BUCKETS     = 5
MAX_UNDERREP_REGIMES       = 5


# ─── Output paths ────────────────────────────────────────────────────────────

def _plans_dir() -> Path:
    override = os.environ.get("EXPERIMENT_PLANS_DIR")
    if override:
        return Path(override)
    return _REPO_ROOT / "learning-loop" / "experiment_plans"


def _docs_dir() -> Path:
    override = os.environ.get("EXPERIMENT_PLANS_DOCS_DIR")
    if override:
        return Path(override)
    return _REPO_ROOT / "docs"


def _ensure_dir(p: Path) -> None:
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        return


# ─── Time helpers ────────────────────────────────────────────────────────────

def _safe_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_today_iso() -> str:
    return _safe_now().date().isoformat()


# ─── Safe coercion ───────────────────────────────────────────────────────────

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


def _safe_str(x: Any, default: str = "") -> str:
    if x is None:
        return default
    if isinstance(x, str):
        return x
    try:
        return str(x)
    except Exception:
        return default


def _safe_iter(x: Any) -> Iterable:
    if x is None:
        return ()
    if isinstance(x, (list, tuple, set, frozenset)):
        return x
    if isinstance(x, Mapping):
        return x.items()
    return ()


# ─── Strategy ranking → strategies_to_observe ────────────────────────────────

def _normalize_ranking(ranking: Any) -> list[dict]:
    """Accept list[dict] or dict-keyed metric mappings.

    Sort by score ASC (worst first) for "needs more data" semantics, then
    by strategy name ASC for tie-break determinism. We surface the
    strategies that learning would gain most from observing — that means
    LOW score (needs data) and CONTINUE/REDUCE statuses come first.
    """
    out: list[dict] = []
    if isinstance(ranking, list):
        for item in ranking:
            if not isinstance(item, Mapping):
                continue
            out.append({
                "strategy": _safe_str(item.get("strategy")),
                "status":   _safe_str(item.get("status")),
                "score":    _safe_float(item.get("score"), 0.0),
                "rank":     _safe_int(item.get("rank"), 0),
            })
    elif isinstance(ranking, Mapping):
        for k, v in ranking.items():
            if isinstance(v, Mapping):
                out.append({
                    "strategy": _safe_str(k),
                    "status":   _safe_str(v.get("status")),
                    "score":    _safe_float(v.get("score"), 0.0),
                    "rank":     _safe_int(v.get("rank"), 0),
                })

    # Discard rows without a strategy name.
    out = [r for r in out if r["strategy"]]
    # Deterministic sort: score ASC, then strategy name ASC.
    out.sort(key=lambda r: (r["score"], r["strategy"]))
    return out


def _select_strategies_to_observe(ranking_rows: Sequence[Mapping]) -> list[dict]:
    """Pick at most MAX_STRATEGIES_OBSERVE rows.

    Priority:
      1. NEEDS_MORE_DATA  (low evidence)
      2. CONTINUE_OBSERVE
      3. REDUCE_PRIORITY
      4. EDGE_REVIEW_CANDIDATE
      5. TOP_OBSERVE
      6. DISABLE_CANDIDATE (last — already flagged)
    """
    priority_map = {
        "NEEDS_MORE_DATA":       0,
        "CONTINUE_OBSERVE":      1,
        "REDUCE_PRIORITY":       2,
        "EDGE_REVIEW_CANDIDATE": 3,
        "TOP_OBSERVE":           4,
        "DISABLE_CANDIDATE":     5,
    }
    annotated = []
    for r in ranking_rows:
        annotated.append({
            **r,
            "_pri": priority_map.get(_safe_str(r.get("status")), 99),
        })
    annotated.sort(key=lambda r: (r["_pri"], r["score"], r["strategy"]))
    picked: list[dict] = []
    for r in annotated[:MAX_STRATEGIES_OBSERVE]:
        picked.append({
            "strategy": r["strategy"],
            "status":   r["status"],
            "score":    round(r["score"], 6),
            "reason":   f"priority={r['_pri']} ({r['status'] or 'unknown'})",
        })
    return picked


# ─── Opportunity ledger → symbols_to_observe + rejected_signals ──────────────

def _normalize_opportunity_ledger(ledger: Any) -> list[dict]:
    """Accept various shapes. Each item must minimally have `symbol`."""
    out: list[dict] = []
    if isinstance(ledger, Mapping):
        # {"opportunities": [...]} or {"rejected_signals": [...]}
        for key in ("opportunities", "rejected_signals", "items", "entries"):
            v = ledger.get(key)
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, Mapping):
                        out.append(dict(item))
        # Also accept symbol-keyed mapping.
        if not out:
            for sym, val in ledger.items():
                if isinstance(val, Mapping):
                    d = dict(val)
                    d.setdefault("symbol", _safe_str(sym))
                    out.append(d)
    elif isinstance(ledger, list):
        for item in ledger:
            if isinstance(item, Mapping):
                out.append(dict(item))
    return [d for d in out if _safe_str(d.get("symbol"))]


def _select_symbols_to_observe(items: Sequence[Mapping]) -> list[dict]:
    """Pick most-frequent symbols (descending), capped + alphabetised on tie."""
    counts: dict[str, int] = {}
    last_seen: dict[str, str] = {}
    for it in items:
        sym = _safe_str(it.get("symbol")).upper()
        if not sym:
            continue
        counts[sym] = counts.get(sym, 0) + 1
        ts = _safe_str(it.get("ts") or it.get("timestamp") or "")
        if ts:
            cur = last_seen.get(sym, "")
            if ts > cur:
                last_seen[sym] = ts
    rows = [{"symbol": s, "occurrences": n, "last_seen": last_seen.get(s, "")}
            for s, n in counts.items()]
    # Deterministic: by count DESC, then symbol ASC.
    rows.sort(key=lambda r: (-r["occurrences"], r["symbol"]))
    return rows[:MAX_SYMBOLS_OBSERVE]


def _select_rejected_signals(items: Sequence[Mapping]) -> list[dict]:
    """Items flagged with a rejection_reason are deemed `rejected_signals`."""
    candidates: list[dict] = []
    for it in items:
        reason = _safe_str(it.get("rejection_reason") or it.get("reason"))
        if not reason:
            continue
        candidates.append({
            "symbol":   _safe_str(it.get("symbol")).upper(),
            "strategy": _safe_str(it.get("strategy")),
            "reason":   reason,
            "ts":       _safe_str(it.get("ts") or it.get("timestamp") or ""),
        })
    # Deterministic: oldest first by ts, then by symbol+strategy.
    candidates.sort(key=lambda r: (r["ts"], r["symbol"], r["strategy"]))
    return candidates[:MAX_REJECTED_SIGNALS]


# ─── Quarantined variants → variants_to_replay ───────────────────────────────

def _load_quarantined_variants_safe() -> list[dict]:
    """Best-effort import + call. Returns [] on any failure."""
    try:
        try:
            from strategy_variant_quarantine import load_quarantined_variants  # type: ignore
        except ImportError:
            from shared.strategy_variant_quarantine import load_quarantined_variants  # type: ignore
        rows = load_quarantined_variants()
        if not isinstance(rows, list):
            return []
        return [r for r in rows if isinstance(r, Mapping)]
    except Exception:
        return []


def _select_variants_to_replay(variants: Sequence[Mapping]) -> list[dict]:
    """Surface variants in QUARANTINED + REPLAY_TESTING states.

    We do NOT surface REJECTED variants. We do NOT surface
    CANDIDATE_FOR_MANUAL_REVIEW (the manual review queue handles those).
    """
    surfaceable = {"QUARANTINED", "REPLAY_TESTING", "SHADOW_OBSERVE"}
    rows = []
    for v in variants:
        status = _safe_str(v.get("status"))
        if status not in surfaceable:
            continue
        rows.append({
            "id":              _safe_str(v.get("id")),
            "parent_strategy": _safe_str(v.get("parent_strategy")),
            "status":          status,
            "evidence_source": _safe_str(v.get("evidence_source")),
            "change_rationale": _safe_str(v.get("change_rationale"))[:160],
        })
    rows.sort(key=lambda r: (r["parent_strategy"], r["id"]))
    return rows[:MAX_VARIANTS_REPLAY]


# ─── Confidence calibration → buckets needing data ───────────────────────────

def _select_confidence_buckets(calibration: Any) -> list[dict]:
    """Buckets with low sample count or |observed - expected| spread.

    Accepts shapes:
      {bucket_label: {n: int, observed_win_rate: float, expected_win_rate: float}}
      [{label, n, observed_win_rate, expected_win_rate}, ...]
    """
    rows: list[dict] = []
    if isinstance(calibration, Mapping):
        for k, v in calibration.items():
            if not isinstance(v, Mapping):
                continue
            rows.append({
                "label":             _safe_str(k),
                "n":                 _safe_int(v.get("n")),
                "observed_win_rate": _safe_float(v.get("observed_win_rate")),
                "expected_win_rate": _safe_float(v.get("expected_win_rate")),
            })
    elif isinstance(calibration, list):
        for item in calibration:
            if not isinstance(item, Mapping):
                continue
            rows.append({
                "label":             _safe_str(item.get("label")),
                "n":                 _safe_int(item.get("n")),
                "observed_win_rate": _safe_float(item.get("observed_win_rate")),
                "expected_win_rate": _safe_float(item.get("expected_win_rate")),
            })
    # Score: prioritise low sample count AND large absolute calibration error.
    for r in rows:
        spread = abs(r["observed_win_rate"] - r["expected_win_rate"])
        # higher score → needs more data
        r["_priority_score"] = (1000 - min(r["n"], 1000)) + (spread * 100)
    rows = [r for r in rows if r["label"]]
    # Deterministic sort: priority DESC, then label ASC.
    rows.sort(key=lambda r: (-r["_priority_score"], r["label"]))
    out = []
    for r in rows[:MAX_CONFIDENCE_BUCKETS]:
        out.append({
            "label":             r["label"],
            "n":                 r["n"],
            "observed_win_rate": round(r["observed_win_rate"], 4),
            "expected_win_rate": round(r["expected_win_rate"], 4),
        })
    return out


# ─── Evidence lower bounds → underrepresented regimes ────────────────────────

def _select_underrepresented_regimes(bounds: Any) -> list[dict]:
    """Regimes where any strategy has too little evidence.

    Accepts:
      {"per_regime": {regime_label: {n_closed: int, min_required: int}, ...}}
      [{label, n_closed, min_required}, ...]
    """
    rows: list[dict] = []
    if isinstance(bounds, Mapping):
        per_regime = bounds.get("per_regime") if "per_regime" in bounds \
            else bounds
        if isinstance(per_regime, Mapping):
            for k, v in per_regime.items():
                if not isinstance(v, Mapping):
                    continue
                rows.append({
                    "regime":       _safe_str(k),
                    "n_closed":     _safe_int(v.get("n_closed")),
                    "min_required": _safe_int(v.get("min_required"), 10),
                })
    elif isinstance(bounds, list):
        for item in bounds:
            if not isinstance(item, Mapping):
                continue
            rows.append({
                "regime":       _safe_str(item.get("label")
                                            or item.get("regime")),
                "n_closed":     _safe_int(item.get("n_closed")),
                "min_required": _safe_int(item.get("min_required"), 10),
            })
    rows = [r for r in rows if r["regime"]
            and r["n_closed"] < r["min_required"]]
    # Deterministic: smallest n first, then regime ASC.
    rows.sort(key=lambda r: (r["n_closed"], r["regime"]))
    return rows[:MAX_UNDERREP_REGIMES]


# ─── Public API: generate_plan ───────────────────────────────────────────────

def generate_plan(
    *,
    strategy_ranking: Any = None,
    opportunity_ledger: Any = None,
    confidence_calibration: Any = None,
    evidence_lower_bounds: Any = None,
    quarantined_variants: Sequence[Mapping] | None = None,
    now: datetime | None = None,
) -> dict:
    """Build a deterministic observation plan.

    All inputs are optional. Missing inputs simply produce empty sections;
    the function NEVER raises and NEVER places trades.

    Parameters
    ----------
    strategy_ranking : list[dict] | dict | None
        Output of `shared/strategy_ranking.py::rank_strategies` or a
        compatible mapping. Used to fill `strategies_to_observe`.
    opportunity_ledger : list[dict] | dict | None
        Either a list of opportunity dicts or a dict containing
        `opportunities` / `rejected_signals`. Used to fill
        `symbols_to_observe` + `rejected_signals_to_analyze`.
    confidence_calibration : list[dict] | dict | None
        Per-bucket calibration data (count + observed vs expected
        win-rate). Used to fill `confidence_buckets_needing_data`.
    evidence_lower_bounds : list[dict] | dict | None
        Per-regime sample counts and minimum required. Used to fill
        `underrepresented_regimes`.
    quarantined_variants : Sequence[Mapping] | None
        Variants from the quarantine module. If None, the scheduler
        attempts a best-effort import; on failure it just returns an
        empty list (the runtime trading path is never affected).
    now : datetime, optional
        Override for determinism in tests.
    """
    now = now or _safe_now()
    plan_date = now.date().isoformat()

    # ── strategies_to_observe ────────────────────────────────────────
    ranking_rows = _normalize_ranking(strategy_ranking)
    strategies_to_observe = _select_strategies_to_observe(ranking_rows)

    # ── symbols + rejected_signals ───────────────────────────────────
    ledger_items = _normalize_opportunity_ledger(opportunity_ledger)
    symbols_to_observe = _select_symbols_to_observe(ledger_items)
    rejected_signals_to_analyze = _select_rejected_signals(ledger_items)

    # ── variants_to_replay ───────────────────────────────────────────
    variants = list(quarantined_variants) \
        if quarantined_variants is not None \
        else _load_quarantined_variants_safe()
    variants_to_replay = _select_variants_to_replay(variants)

    # ── confidence buckets ───────────────────────────────────────────
    confidence_buckets = _select_confidence_buckets(confidence_calibration)

    # ── underrepresented regimes ─────────────────────────────────────
    underrepresented_regimes = _select_underrepresented_regimes(
        evidence_lower_bounds)

    plan: dict = {
        "ts_iso":                       now.isoformat(),
        "plan_date":                    plan_date,
        "strategies_to_observe":        strategies_to_observe,
        "symbols_to_observe":           symbols_to_observe,
        "variants_to_replay":           variants_to_replay,
        "rejected_signals_to_analyze":  rejected_signals_to_analyze,
        "confidence_buckets_needing_data": confidence_buckets,
        "underrepresented_regimes":     underrepresented_regimes,
        "invariants":                   dict(INVARIANTS),
        "notes": [
            "scheduler does not place trades",
            "scheduler does not raise risk",
            "scheduler does not change gates",
            "evidence sources: BACKTEST + REPLAY for variants; "
            "PAPER for paper metrics; never mixed",
        ],
    }
    return plan


# ─── Public API: write_plan_to_disk ──────────────────────────────────────────

def _render_markdown(plan: Mapping) -> str:
    """Render the markdown summary for docs/experiment_plan_LATEST.md."""
    lines: list[str] = []
    lines.append(f"# Experiment plan ({plan.get('plan_date', 'unknown')})")
    lines.append("")
    lines.append(f"_Generated: {plan.get('ts_iso', '')}_")
    lines.append("")
    lines.append("This plan is OBSERVATION-ONLY. It does not place trades,")
    lines.append("raise risk, or change gates.")
    lines.append("")

    def _section(title: str, rows: Sequence[Mapping],
                 columns: Sequence[str]) -> None:
        lines.append(f"## {title}")
        lines.append("")
        if not rows:
            lines.append("_(empty)_")
            lines.append("")
            return
        header = "| " + " | ".join(columns) + " |"
        sep = "| " + " | ".join(["---"] * len(columns)) + " |"
        lines.append(header)
        lines.append(sep)
        for r in rows:
            cells = [str(r.get(c, "")) for c in columns]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    _section("Strategies to observe",
             plan.get("strategies_to_observe") or [],
             ["strategy", "status", "score", "reason"])
    _section("Symbols to observe",
             plan.get("symbols_to_observe") or [],
             ["symbol", "occurrences", "last_seen"])
    _section("Variants to replay (quarantined / replay testing only)",
             plan.get("variants_to_replay") or [],
             ["id", "parent_strategy", "status", "evidence_source",
              "change_rationale"])
    _section("Rejected signals to analyze",
             plan.get("rejected_signals_to_analyze") or [],
             ["symbol", "strategy", "reason", "ts"])
    _section("Confidence buckets needing data",
             plan.get("confidence_buckets_needing_data") or [],
             ["label", "n", "observed_win_rate", "expected_win_rate"])
    _section("Underrepresented regimes",
             plan.get("underrepresented_regimes") or [],
             ["regime", "n_closed", "min_required"])

    lines.append("## Invariants")
    lines.append("")
    for k, v in (plan.get("invariants") or {}).items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    return "\n".join(lines)


def write_plan_to_disk(plan: Mapping) -> list[Path]:
    """Persist plan JSON + markdown. Returns paths written.

    Fail-soft: returns whatever was successfully written.
    """
    written: list[Path] = []
    plan_date = _safe_str(plan.get("plan_date"), _utc_today_iso())

    plans_dir = _plans_dir()
    _ensure_dir(plans_dir)
    json_path = plans_dir / f"experiment_plan_{plan_date}.json"
    try:
        json_path.write_text(
            json.dumps(plan, indent=2, sort_keys=True, default=str),
            encoding="utf-8")
        written.append(json_path)
    except OSError:
        pass

    docs_dir = _docs_dir()
    _ensure_dir(docs_dir)
    md_path = docs_dir / "experiment_plan_LATEST.md"
    try:
        md_path.write_text(_render_markdown(plan), encoding="utf-8")
        written.append(md_path)
    except OSError:
        pass

    return written


# ─── Audit emission (fail-soft) ──────────────────────────────────────────────

def emit_audit_event(event_type: str, plan_summary: Mapping) -> None:
    """Best-effort audit. Never raises into caller."""
    try:
        try:
            from audit import write_audit_event           # type: ignore
            from autonomy import make_decision            # type: ignore
        except ImportError:
            from shared.audit import write_audit_event    # type: ignore
            from shared.autonomy import make_decision     # type: ignore
        d = make_decision(
            decision_type="RESUME_STRATEGY",
            decision="EXPERIMENT_PLAN_GENERATED",
            reason=f"experiment-scheduler: {event_type}",
            actor="experiment-scheduler",
            risk_metrics={
                "strategies_to_observe_n": len(plan_summary.get(
                    "strategies_to_observe", []) or []),
                "symbols_to_observe_n": len(plan_summary.get(
                    "symbols_to_observe", []) or []),
                "variants_to_replay_n": len(plan_summary.get(
                    "variants_to_replay", []) or []),
                "rejected_signals_n": len(plan_summary.get(
                    "rejected_signals_to_analyze", []) or []),
            },
            reversible=True,
        )
        write_audit_event(d, kind="trading")
    except Exception:
        return


__all__ = [
    # invariants
    "SCHEDULER_NEVER_PLACES_TRADES",
    "SCHEDULER_NEVER_RAISES_RISK",
    "SCHEDULER_NEVER_CHANGES_GATES",
    "INVARIANTS",
    # caps
    "MAX_STRATEGIES_OBSERVE",
    "MAX_SYMBOLS_OBSERVE",
    "MAX_VARIANTS_REPLAY",
    "MAX_REJECTED_SIGNALS",
    "MAX_CONFIDENCE_BUCKETS",
    "MAX_UNDERREP_REGIMES",
    # API
    "generate_plan",
    "write_plan_to_disk",
    "emit_audit_event",
]
