#!/usr/bin/env python3
"""v3.26 (Agent 3A ETAP 3) — Strategy threshold reality report.

Reads the last 7 days of ``learning-loop/opportunity_ledger/*.jsonl``
rows and asks, per (strategy, symbol) pair, whether the strategy's
gating thresholds are realistic given the data we actually observed.

PER-STRATEGY METRICS
--------------------
For each known strategy we extract its gating metric from each row's
``raw_signal`` field:

    crypto-oversold-bounce: rsi (vs threshold 30, direction below)
    crypto-momentum:        rsi (vs threshold 60, direction above)
                            24h_move (vs predator bracket [3%, 15%])
    momentum-long:          rsi (vs 50/70 band),
                            volume_ratio (vs 1.5×),
                            breakout_pct (vs +2%)
    momentum-long-loose:    rsi (vs 45/75 band)
    overbought-short:       rsi (vs 72)

Per strategy we compute:

    evaluations            — rows tagged with this strategy
    actual_signals_fired   — rows whose raw_signal.action is BUY or
                             SELL_SHORT (rare today)
    near_misses            — evaluations within 10% of trigger
    avg_distance_to_trigger
    threshold_realism      — REALISTIC | TOO_STRICT | TOO_LOOSE |
                             INSUFFICIENT_DATA
    recommendation         — KEEP | OBSERVE_MORE |
                             SHADOW_VARIANT_REVIEW |
                             REPLAY_TEST_VARIANT |
                             DISABLE_CANDIDATE |
                             NEEDS_OPERATOR_REVIEW

OUTPUTS
-------
- ``learning-loop/strategy_threshold_reality_latest.json``
- ``docs/STRATEGY_THRESHOLD_REALITY.md`` (operator table)

HARD SAFETY (re-asserted)
-------------------------
- NEVER auto-adjusts a strategy threshold.
- NEVER imports ``alpaca_orders``.
- NEVER makes a broker or network call.
- NEVER counts a ledger row as a paper trade outcome.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent

VERSION = "v3.26.0"

# ──────────────────────────────────────────────────────────────────────────────
# Strategy threshold catalogue.
#
# Each entry maps a strategy_id to a list of *(metric_name, threshold,
# direction)* tuples. ``direction`` is "above", "below", or "between"
# (for bracket-style filters such as crypto-momentum's 24h_move).
# ──────────────────────────────────────────────────────────────────────────────

STRATEGY_GATES: dict[str, list[tuple[str, Any, str]]] = {
    "crypto-oversold-bounce": [
        ("rsi", 30.0, "below"),
    ],
    "crypto-momentum": [
        ("rsi",          60.0,             "above"),
        ("move_24h_pct", (3.0, 15.0),      "between"),
    ],
    "momentum-long": [
        ("rsi",          (50.0, 70.0),     "between"),
        ("breakout_pct", 0.02,             "above"),
        ("volume_ratio", 1.5,              "above"),
    ],
    "momentum-long-loose": [
        ("rsi",          (45.0, 75.0),     "between"),
        ("breakout_pct", 0.02,             "above"),
    ],
    "overbought-short": [
        ("rsi",          72.0,             "above"),
    ],
}

# Near-miss = within this percentage of the threshold.
NEAR_MISS_PCT = 0.10

# Sample-size cutoffs.
MIN_EVAL_REALISM = 30      # below this, realism = INSUFFICIENT_DATA
MIN_EVAL_RECOMMENDATION = 50

# Standing markers (re-emitted at the bottom of every artifact).
HARD_SAFETY_MARKERS = [
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "NO_THRESHOLD_AUTO_CHANGE",
    "NO_BROKER_CALL",
    "NO_PROMOTION",
    "REPORTER_VERSION={ver}",
]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _safe_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
        if v != v:    # NaN
            return None
        return v
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _ledger_dir() -> Path:
    return REPO_ROOT / "learning-loop" / "opportunity_ledger"


def _load_recent_rows(days: int = 7,
                      as_of: datetime | None = None,
                      base_dir: Path | None = None) -> list[dict]:
    """Read the last ``days`` JSONL ledger files. Fail-soft on any
    individual file."""
    if as_of is None:
        as_of = datetime.now(timezone.utc)
    base = base_dir if base_dir is not None else _ledger_dir()
    rows: list[dict] = []
    for delta in range(days):
        d = (as_of - timedelta(days=delta)).date()
        f = base / f"{d.isoformat()}.jsonl"
        if not f.exists():
            continue
        try:
            with f.open(encoding="utf-8") as fp:
                for line in fp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue
    return rows


def _within_near_miss(metric_value: float,
                      threshold: Any,
                      direction: str) -> tuple[bool, float, bool]:
    """Return (is_near_miss, signed_distance, hit_trigger).

    ``signed_distance`` is metric_value - threshold (or per-bound for
    "between"; positive means above the upper bound, negative below
    the lower bound).
    ``hit_trigger`` indicates the metric actually fired (not a miss).
    """
    if direction == "above":
        thr = float(threshold)
        if thr == 0.0:
            return (False, metric_value, metric_value > 0)
        dist = metric_value - thr
        hit = metric_value > thr
        if hit:
            return (False, dist, True)
        # Below threshold — is the distance within the window?
        within = abs(dist) <= NEAR_MISS_PCT * abs(thr)
        return (within, dist, False)

    if direction == "below":
        thr = float(threshold)
        if thr == 0.0:
            return (False, metric_value, metric_value < 0)
        dist = metric_value - thr
        hit = metric_value < thr
        if hit:
            return (False, dist, True)
        within = abs(dist) <= NEAR_MISS_PCT * abs(thr)
        return (within, dist, False)

    if direction == "between":
        lo, hi = threshold     # tuple
        lo_f, hi_f = float(lo), float(hi)
        hit = lo_f <= metric_value <= hi_f
        if hit:
            return (False, 0.0, True)
        # Miss — compute distance to nearest bound.
        if metric_value < lo_f:
            dist = metric_value - lo_f
            ref = abs(lo_f)
        else:
            dist = metric_value - hi_f
            ref = abs(hi_f)
        if ref == 0.0:
            return (False, dist, False)
        within = abs(dist) <= NEAR_MISS_PCT * ref
        return (within, dist, False)

    # Unknown direction — never near-miss.
    return (False, 0.0, False)


def _row_action_fired(row: dict) -> bool:
    """Return True iff the row recorded an actual entry-side action."""
    raw = row.get("raw_signal") or {}
    action = str(raw.get("action") or row.get("paper_action") or "").upper()
    return action in {"BUY", "SELL_SHORT", "SELL"}


# ──────────────────────────────────────────────────────────────────────────────
# Per-strategy aggregation
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class StrategyMetricAggregate:
    strategy_id: str
    metric_name: str
    threshold: Any
    direction: str
    sample_size: int = 0
    near_misses: int = 0
    actual_hits: int = 0
    distances: list[float] = field(default_factory=list)

    def summarize(self) -> dict:
        n = self.sample_size
        avg_distance = (sum(self.distances) / n) if n else 0.0
        miss_rate = (self.near_misses / n) if n else 0.0
        hit_rate = (self.actual_hits / n) if n else 0.0

        realism = _classify_realism(
            sample_size=n,
            near_misses=self.near_misses,
            actual_hits=self.actual_hits,
        )
        return {
            "strategy_id":             self.strategy_id,
            "metric_name":             self.metric_name,
            "threshold":               self.threshold,
            "direction":               self.direction,
            "sample_size":             n,
            "near_misses":             self.near_misses,
            "actual_hits":             self.actual_hits,
            "near_miss_rate":          round(miss_rate, 4),
            "hit_rate":                round(hit_rate, 4),
            "avg_distance_to_trigger": round(avg_distance, 6),
            "threshold_realism":       realism,
        }


def _classify_realism(*, sample_size: int, near_misses: int,
                      actual_hits: int) -> str:
    """Classify per-metric realism. Pure read-only.

    - INSUFFICIENT_DATA: sample_size < MIN_EVAL_REALISM
    - TOO_LOOSE:        hit_rate >= 0.50  (more than half of evals fired)
    - REALISTIC:        hit_rate or near-miss rate in 5%-30%
    - TOO_STRICT:       hit_rate == 0 AND near_miss_rate <= 0.10
    - REALISTIC (else)
    """
    if sample_size < MIN_EVAL_REALISM:
        return "INSUFFICIENT_DATA"
    hit_rate = actual_hits / sample_size
    miss_rate = near_misses / sample_size
    if hit_rate >= 0.50:
        return "TOO_LOOSE"
    if hit_rate == 0.0 and miss_rate <= 0.10:
        return "TOO_STRICT"
    return "REALISTIC"


def _recommend_for_strategy(strategy_id: str,
                            evaluations: int,
                            actual_signals_fired: int,
                            near_misses: int,
                            metric_realisms: list[str]) -> str:
    """Operator-facing recommendation (advisory only).

    Sample-size guarded so that a sub-50-row strategy is never sent
    to DISABLE_CANDIDATE.
    """
    if evaluations < MIN_EVAL_RECOMMENDATION:
        return "OBSERVE_MORE"

    too_strict = sum(1 for r in metric_realisms if r == "TOO_STRICT")
    too_loose = sum(1 for r in metric_realisms if r == "TOO_LOOSE")
    realistic = sum(1 for r in metric_realisms if r == "REALISTIC")

    # No real fires, no near-misses → strategy may be broken or
    # fundamentally inactive in this regime.
    if actual_signals_fired == 0 and near_misses == 0:
        return "DISABLE_CANDIDATE"

    # No real fires but plenty of near-misses → threshold likely too strict.
    if actual_signals_fired == 0 and near_misses >= 5:
        return "SHADOW_VARIANT_REVIEW"

    # Some near-misses + at least one TOO_STRICT metric.
    if too_strict >= 1 and near_misses >= 3:
        return "SHADOW_VARIANT_REVIEW"

    # Strategy is firing but realism mixed → worth replay-testing a variant.
    if actual_signals_fired >= 1 and too_loose >= 1:
        return "REPLAY_TEST_VARIANT"

    # Mostly realistic → KEEP.
    if realistic >= 1 and too_loose == 0 and too_strict == 0:
        return "KEEP"

    # Anything else → operator should look.
    return "NEEDS_OPERATOR_REVIEW"


# ──────────────────────────────────────────────────────────────────────────────
# Core aggregator
# ──────────────────────────────────────────────────────────────────────────────

def aggregate_rows(rows: Iterable[dict]) -> dict:
    """Group rows by strategy_id, then by (strategy, metric).

    Returns the structured aggregate. PURE; no I/O.
    """
    # buckets: strategy_id -> metric_name -> StrategyMetricAggregate
    buckets: dict[str, dict[str, StrategyMetricAggregate]] = {}
    # per-strategy event counters
    per_strategy_eval: dict[str, int] = {}
    per_strategy_fired: dict[str, int] = {}

    for row in rows:
        if not isinstance(row, dict):
            continue
        strategy_id = str(row.get("strategy") or "").strip()
        if not strategy_id or strategy_id not in STRATEGY_GATES:
            continue
        per_strategy_eval[strategy_id] = per_strategy_eval.get(strategy_id, 0) + 1
        if _row_action_fired(row):
            per_strategy_fired[strategy_id] = per_strategy_fired.get(strategy_id, 0) + 1
        raw = row.get("raw_signal") or {}
        if not isinstance(raw, dict):
            continue
        for (metric_name, threshold, direction) in STRATEGY_GATES[strategy_id]:
            val = _safe_float(raw.get(metric_name))
            if val is None:
                continue
            agg = (buckets.setdefault(strategy_id, {})
                          .setdefault(metric_name,
                                      StrategyMetricAggregate(
                                          strategy_id=strategy_id,
                                          metric_name=metric_name,
                                          threshold=threshold,
                                          direction=direction)))
            agg.sample_size += 1
            within, dist, hit = _within_near_miss(val, threshold, direction)
            agg.distances.append(float(dist))
            if hit:
                agg.actual_hits += 1
            elif within:
                agg.near_misses += 1

    # Summarise.
    strategies_out: list[dict] = []
    for strategy_id, gates in STRATEGY_GATES.items():
        metric_summaries: list[dict] = []
        metric_realisms: list[str] = []
        per_strategy_near_misses = 0
        for (metric_name, _thr, _dir) in gates:
            agg = (buckets.get(strategy_id) or {}).get(metric_name)
            if agg is None:
                continue
            s = agg.summarize()
            metric_summaries.append(s)
            metric_realisms.append(s["threshold_realism"])
            per_strategy_near_misses += int(s.get("near_misses", 0))

        evaluations = per_strategy_eval.get(strategy_id, 0)
        actual = per_strategy_fired.get(strategy_id, 0)
        recommendation = _recommend_for_strategy(
            strategy_id=strategy_id,
            evaluations=evaluations,
            actual_signals_fired=actual,
            near_misses=per_strategy_near_misses,
            metric_realisms=metric_realisms,
        )
        # Strategy-level realism is the worst of its metric realisms,
        # with INSUFFICIENT_DATA dominating.
        if not metric_realisms:
            strategy_realism = "INSUFFICIENT_DATA"
        elif "INSUFFICIENT_DATA" in metric_realisms:
            strategy_realism = "INSUFFICIENT_DATA"
        elif "TOO_STRICT" in metric_realisms:
            strategy_realism = "TOO_STRICT"
        elif "TOO_LOOSE" in metric_realisms:
            strategy_realism = "TOO_LOOSE"
        else:
            strategy_realism = "REALISTIC"

        strategies_out.append({
            "strategy_id":          strategy_id,
            "evaluations":          evaluations,
            "actual_signals_fired": actual,
            "near_misses":          per_strategy_near_misses,
            "threshold_realism":    strategy_realism,
            "recommendation":       recommendation,
            "metrics":              metric_summaries,
        })

    return {
        "version":          VERSION,
        "generated_at_iso": _now_iso(),
        "window_days":      7,
        "params": {
            "near_miss_pct":            NEAR_MISS_PCT,
            "min_eval_realism":         MIN_EVAL_REALISM,
            "min_eval_recommendation":  MIN_EVAL_RECOMMENDATION,
        },
        "strategies":       strategies_out,
        "row_count":        sum(per_strategy_eval.values()),
        "hard_safety": {
            "auto_threshold_change":  False,
            "broker_call_made":       False,
            "promotion_to_active":    False,
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Renderers
# ──────────────────────────────────────────────────────────────────────────────

def _render_markdown(report: dict) -> str:
    """Render an operator-friendly markdown table.

    Standing markers are repeated in the footer so an operator skimming
    a single page always sees the safety invariants."""
    lines: list[str] = []
    lines.append("# Strategy threshold reality")
    lines.append("")
    lines.append(f"**Reporter version:** {report.get('version', VERSION)}")
    lines.append(f"**Generated at (UTC):** `{report.get('generated_at_iso', '?')}`")
    lines.append(f"**Window:** last {report.get('window_days', 7)} days "
                 f"(`{report.get('row_count', 0)}` ledger rows scanned)")
    lines.append("")
    lines.append("> Recommendations are **advisory only**. This module "
                 "NEVER auto-adjusts a threshold, NEVER promotes a "
                 "variant to active, NEVER makes a broker or network call.")
    lines.append("")

    # Per-strategy summary table.
    lines.append("## Per-strategy summary")
    lines.append("")
    lines.append("| Strategy | Evals | Fired | Near-misses | Realism | Recommendation |")
    lines.append("|----------|------:|------:|------------:|---------|----------------|")
    for s in report.get("strategies", []):
        lines.append(
            "| `{sid}` | {ev} | {fr} | {nm} | {rl} | {rc} |".format(
                sid=s.get("strategy_id", "?"),
                ev=s.get("evaluations", 0),
                fr=s.get("actual_signals_fired", 0),
                nm=s.get("near_misses", 0),
                rl=s.get("threshold_realism", "?"),
                rc=s.get("recommendation", "?"),
            )
        )

    # Per-metric detail.
    lines.append("")
    lines.append("## Per-metric detail")
    lines.append("")
    lines.append("| Strategy | Metric | Threshold | Direction | Samples |"
                 " Near-misses | Hits | Avg dist | Realism |")
    lines.append("|----------|--------|-----------|-----------|--------:|"
                 "------------:|-----:|---------:|---------|")
    for s in report.get("strategies", []):
        for m in s.get("metrics", []):
            thr = m.get("threshold")
            if isinstance(thr, list):
                thr_s = f"[{thr[0]}, {thr[1]}]"
            elif isinstance(thr, tuple):
                thr_s = f"[{thr[0]}, {thr[1]}]"
            else:
                thr_s = f"{thr}"
            lines.append(
                "| `{sid}` | `{mn}` | {thr} | {dir} | {ss} | {nm} | {hit} |"
                " {ad:.4f} | {rl} |".format(
                    sid=s.get("strategy_id", "?"),
                    mn=m.get("metric_name", "?"),
                    thr=thr_s,
                    dir=m.get("direction", "?"),
                    ss=m.get("sample_size", 0),
                    nm=m.get("near_misses", 0),
                    hit=m.get("actual_hits", 0),
                    ad=float(m.get("avg_distance_to_trigger", 0.0)),
                    rl=m.get("threshold_realism", "?"),
                )
            )

    lines.append("")
    lines.append("## Standing safety markers")
    lines.append("")
    for marker in HARD_SAFETY_MARKERS:
        lines.append(f"- `{marker.format(ver=report.get('version', VERSION))}`")
    lines.append("")
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def build_report(*, days: int = 7,
                 as_of: datetime | None = None,
                 ledger_dir: Path | None = None) -> dict:
    """Return the structured report dict. Pure / no I/O after read."""
    rows = _load_recent_rows(days=days, as_of=as_of, base_dir=ledger_dir)
    return aggregate_rows(rows)


def write_report(report: dict,
                 *,
                 json_path: Path | None = None,
                 md_path: Path | None = None) -> tuple[Path, Path]:
    """Persist JSON + Markdown artifacts. Return the two paths."""
    jp = (json_path if json_path is not None
          else REPO_ROOT / "learning-loop" / "strategy_threshold_reality_latest.json")
    mp = (md_path if md_path is not None
          else REPO_ROOT / "docs" / "STRATEGY_THRESHOLD_REALITY.md")
    try:
        jp.parent.mkdir(parents=True, exist_ok=True)
        with jp.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=True, default=str)
            f.write("\n")
    except OSError as e:
        print(f"[strategy-threshold-reality] WARN: could not write {jp}: {e}",
              file=sys.stderr)
    try:
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(_render_markdown(report), encoding="utf-8")
    except OSError as e:
        print(f"[strategy-threshold-reality] WARN: could not write {mp}: {e}",
              file=sys.stderr)
    return jp, mp


def _cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Build the strategy-threshold reality report.",
    )
    p.add_argument("--days", type=int, default=7,
                   help="Window size in days (default 7).")
    p.add_argument("--ledger-dir", type=Path, default=None,
                   help="Override opportunity ledger directory.")
    p.add_argument("--json-out", type=Path, default=None,
                   help="Override JSON output path.")
    p.add_argument("--md-out", type=Path, default=None,
                   help="Override Markdown output path.")
    p.add_argument("--print", action="store_true",
                   help="Print summary to stdout.")
    args = p.parse_args(argv)

    report = build_report(days=args.days, ledger_dir=args.ledger_dir)
    jp, mp = write_report(report, json_path=args.json_out, md_path=args.md_out)

    if args.print:
        for s in report.get("strategies", []):
            print(f"  {s['strategy_id']:<24} "
                  f"evals={s['evaluations']:<5} "
                  f"fired={s['actual_signals_fired']:<3} "
                  f"near={s['near_misses']:<3} "
                  f"realism={s['threshold_realism']:<18} "
                  f"-> {s['recommendation']}")
    print(f"[strategy-threshold-reality] wrote {jp}")
    print(f"[strategy-threshold-reality] wrote {mp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
