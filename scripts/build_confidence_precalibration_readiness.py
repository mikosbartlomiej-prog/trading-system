#!/usr/bin/env python3
"""v3.26 (2026-06-15) — Confidence pre-calibration readiness reporter.

Reads ``learning-loop/opportunity_ledger/<YYYY-MM-DD>.jsonl`` for the
last 7 days. For every entry-capable row with a non-null
``confidence_score`` it computes:

* score distribution (min / median / p95 / max / mean)
* per-component variance (which of the 8 components actually vary vs
  always-default)
* builder_completeness distribution
* counts of ``confidence_decision`` in {ALLOW, ALERT_ONLY, BLOCK, ERROR}

Verdict (one of):
  - NOT_READY_NO_POSITIVE_ROWS
  - READY_FOR_SHADOW_OUTCOMES
  - NEEDS_COMPONENT_VARIANCE
  - NEEDS_MORE_ENTRY_CANDIDATES

Writes:
  - learning-loop/confidence_precalibration_readiness_latest.json
  - docs/CONFIDENCE_PRECALIBRATION_READINESS.md

HARD SAFETY
-----------
- NEVER imports ``alpaca_orders``.
- NEVER makes network calls.
- NEVER mutates strategy thresholds.
- Pure read-only aggregation over the opportunity ledger.
- Standing markers re-asserted in the footer.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

LATEST_JSON_PATH = (REPO_ROOT / "learning-loop"
                    / "confidence_precalibration_readiness_latest.json")
LATEST_MD_PATH = (REPO_ROOT / "docs"
                  / "CONFIDENCE_PRECALIBRATION_READINESS.md")
LEDGER_DIR = REPO_ROOT / "learning-loop" / "opportunity_ledger"

VERSION = "v3.27.0"

# Verdicts (v3.26 backward-compat names kept for snapshot consumers)
VERDICT_NOT_READY            = "NOT_READY_NO_POSITIVE_ROWS"
VERDICT_READY                = "READY_FOR_SHADOW_OUTCOMES"
VERDICT_NEEDS_VARIANCE       = "NEEDS_COMPONENT_VARIANCE"
VERDICT_NEEDS_CANDIDATES     = "NEEDS_MORE_ENTRY_CANDIDATES"

# v3.27 separation verdicts (separate production from replay/near-miss)
VERDICT_V327_NO_POSITIVES     = "NOT_READY_NO_POSITIVE_ROWS"
VERDICT_V327_REPLAY_READY     = "READY_FOR_COMPONENT_VARIANCE_REVIEW"
VERDICT_V327_OUTCOMES_NEEDED  = "READY_FOR_SHADOW_OUTCOME_COLLECTION"
VERDICT_V327_OUTCOMES_PENDING = "NOT_READY_NO_OUTCOMES"

# v3.27 fixture/replay/near-miss paths (read-only)
REPLAY_DISCOVERY_PATH = (REPO_ROOT / "learning-loop"
                         / "replay_discovery_latest.json")
NEAR_MISS_DIR_V327 = REPO_ROOT / "learning-loop" / "near_miss"
SHADOW_EVIDENCE_DIR = REPO_ROOT / "learning-loop" / "shadow_evidence"

# Pre-calibration thresholds (operator-tuneable via CLI)
DEFAULT_MIN_POSITIVE_ROWS              = 30
DEFAULT_MIN_VARYING_COMPONENTS         = 4   # of 8
DEFAULT_VARIANCE_EPSILON               = 1e-9

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES",
    "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
    "CONFIDENCE_PRECALIBRATION_DOES_NOT_TRADE",
    "REPORTER_NEVER_MUTATES_STATE",
    "REPLAY_ROW_NEVER_COUNTS_AS_PRODUCTION_POSITIVE",
    "NEAR_MISS_ROW_NEVER_COUNTS_AS_PRODUCTION_POSITIVE",
    "FIXTURE_ROW_NEVER_COUNTS_AS_PRODUCTION_POSITIVE",
    "CALIBRATION_NEVER_RECOMMENDED_WITHOUT_OUTCOMES",
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True, check=True, text=True, timeout=5,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def _load_ledger_rows(*, as_of: datetime, days: int,
                       base_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not base_dir.exists():
        return rows
    end_date = as_of.date()
    start_date = end_date - timedelta(days=days - 1)
    for path in sorted(base_dir.glob("*.jsonl")):
        # Parse YYYY-MM-DD prefix
        stem = path.stem
        try:
            file_date = datetime.strptime(stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_date < start_date or file_date > end_date:
            continue
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        # Fail-soft: skip malformed rows.
                        continue
        except Exception:
            continue
    return rows


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    vs = sorted(values)
    if len(vs) == 1:
        return float(vs[0])
    k = (len(vs) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(vs[int(k)])
    return float(vs[f] + (vs[c] - vs[f]) * (k - f))


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / (len(values) - 1)


# ─── Aggregation ──────────────────────────────────────────────────────────────


def _summarize_scores(scores: list[float]) -> dict[str, Any]:
    if not scores:
        return {
            "count":  0,
            "min":    None,
            "median": None,
            "p95":    None,
            "max":    None,
            "mean":   None,
        }
    return {
        "count":  len(scores),
        "min":    round(min(scores), 4),
        "median": round(_percentile(scores, 50.0) or 0.0, 4),
        "p95":    round(_percentile(scores, 95.0) or 0.0, 4),
        "max":    round(max(scores), 4),
        "mean":   round(sum(scores) / len(scores), 4),
    }


def _summarize_completeness(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "count":  0,
            "min":    None,
            "median": None,
            "mean":   None,
        }
    return {
        "count":  len(values),
        "min":    round(min(values), 4),
        "median": round(_percentile(values, 50.0) or 0.0, 4),
        "mean":   round(sum(values) / len(values), 4),
    }


def _summarize_components(
    rows: list[dict[str, Any]],
    *,
    variance_eps: float,
) -> dict[str, Any]:
    """Return per-component statistics across positive rows.

    A "varying" component has variance >= variance_eps. A
    "default-only" component has variance below that threshold (we
    treat it as always-default and therefore useless for calibration).
    """
    by_comp: dict[str, list[float]] = {}
    for row in rows:
        comps = row.get("confidence_components") or {}
        if not isinstance(comps, dict):
            continue
        for name, val in comps.items():
            try:
                f = float(val)
            except (TypeError, ValueError):
                continue
            by_comp.setdefault(name, []).append(f)

    summary: dict[str, dict[str, Any]] = {}
    varying = 0
    default_only = 0
    for name, vals in by_comp.items():
        var = _variance(vals)
        is_varying = var >= variance_eps
        if is_varying:
            varying += 1
        else:
            default_only += 1
        summary[name] = {
            "samples":   len(vals),
            "min":       round(min(vals), 4) if vals else None,
            "max":       round(max(vals), 4) if vals else None,
            "mean":      round(sum(vals) / len(vals), 4) if vals else None,
            "variance":  round(var, 6),
            "varying":   is_varying,
        }
    return {
        "per_component":         summary,
        "varying_components":    varying,
        "default_only_components": default_only,
        "total_components_seen": len(summary),
    }


def _decision_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    c = Counter()
    for row in rows:
        d = row.get("confidence_decision")
        if isinstance(d, str) and d:
            c[d] += 1
    return dict(c)


# ─── v3.27 source separation helpers ──────────────────────────────────────────


def _count_replay_positive_rows(
    *,
    replay_path: Path | None = None,
) -> int:
    """Count entry-capable rows from the replay-discovery artefact.

    A "replay positive row" is any record with
    ``evidence_source="REPLAY"`` and a candidate action — those are
    surfaced by ``scripts/replay_entry_candidate_discovery.py``.

    NEVER mistakes a replay row for a production positive: the caller
    keeps the two counts strictly separate.
    """
    if replay_path is None:
        replay_path = REPLAY_DISCOVERY_PATH
    if not replay_path.exists():
        return 0
    try:
        raw = json.loads(replay_path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    total = 0
    rows = raw.get("rows") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        recs = row.get("candidate_records") or []
        if isinstance(recs, list):
            for r in recs:
                if (isinstance(r, dict)
                        and r.get("evidence_source") == "REPLAY"
                        and r.get("action")):
                    total += 1
    return total


def _count_near_miss_rows(
    *,
    base_dir: Path | None = None,
    as_of: datetime,
    days: int = 7,
) -> int:
    """Count near-miss records from ``learning-loop/near_miss/*.jsonl``.

    Near-miss rows by definition NEVER trigger an order. They are
    operator-review hints only and remain segregated from production.
    """
    if base_dir is None:
        base_dir = NEAR_MISS_DIR_V327
    if not base_dir.exists():
        return 0
    count = 0
    end_date = as_of.date()
    start_date = end_date - timedelta(days=days - 1)
    for p in sorted(base_dir.glob("*.jsonl")):
        try:
            file_date = datetime.strptime(p.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_date < start_date or file_date > end_date:
            continue
        try:
            with p.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        json.loads(line)
                        count += 1
                    except Exception:
                        continue
        except Exception:
            continue
    return count


def _count_fixture_only_rows(
    rows: list[dict[str, Any]],
) -> int:
    """Count ledger rows that originated from a v3.26 fixture/test path.

    A "fixture" row is identified by an explicit
    ``evidence_source`` ∈ {"FIXTURE", "TEST_FIXTURE"} or a
    ``signal_id`` matching a test/quarantine prefix. These never
    count as production positives.
    """
    count = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        es = r.get("evidence_source")
        if isinstance(es, str) and es.upper() in (
            "FIXTURE", "TEST_FIXTURE", "QUARANTINE_FIXTURE",
        ):
            count += 1
            continue
        sid = r.get("signal_id")
        if isinstance(sid, str) and (
            sid.startswith("test-")
            or sid.startswith("fixture-")
            or sid.startswith("quarantine-")
        ):
            count += 1
    return count


def _has_outcomes(
    *,
    shadow_dir: Path | None = None,
) -> bool:
    """Detect whether any shadow-evidence outcome record is present.

    Outcomes are required before any confidence calibration can run.
    Without them the verdict ALWAYS lands on
    ``NOT_READY_NO_OUTCOMES``.
    """
    if shadow_dir is None:
        shadow_dir = SHADOW_EVIDENCE_DIR
    if not shadow_dir.exists():
        return False
    # Any file containing a non-empty "outcome" field counts.
    for p in sorted(shadow_dir.glob("*.json")):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(raw, dict) and raw.get("outcome"):
            return True
        if isinstance(raw, dict) and isinstance(raw.get("rows"), list):
            for r in raw["rows"]:
                if isinstance(r, dict) and r.get("outcome"):
                    return True
    return False


def _classify_verdict_v327(
    *,
    production_positive_rows: int,
    replay_positive_rows: int,
    near_miss_rows: int,
    has_outcomes: bool,
) -> tuple[str, str]:
    """v3.27 separation verdict (REFUSES to recommend 'calibrate' without outcomes).

    Precedence:
    1. No positives anywhere → NOT_READY_NO_POSITIVE_ROWS
    2. Replay or near-miss present, no production → READY_FOR_COMPONENT_VARIANCE_REVIEW
    3. Production positives present, NO outcomes → NOT_READY_NO_OUTCOMES
    4. Production positives present, outcomes available → READY_FOR_SHADOW_OUTCOME_COLLECTION
    """
    if (production_positive_rows == 0
            and replay_positive_rows == 0
            and near_miss_rows == 0):
        return (
            VERDICT_V327_NO_POSITIVES,
            ("No positive rows anywhere — production, replay, or "
             "near-miss. Verify Phase-2 wiring and seed local "
             "backfill snapshots."),
        )
    if production_positive_rows == 0:
        return (
            VERDICT_V327_REPLAY_READY,
            (f"{replay_positive_rows} replay row(s) and "
             f"{near_miss_rows} near-miss row(s) available for "
             "component-variance review. NO production positive "
             "rows yet — calibration MUST NOT be attempted; "
             "operator may proceed only to variance review."),
        )
    # production_positive_rows > 0
    if not has_outcomes:
        return (
            VERDICT_V327_OUTCOMES_PENDING,
            (f"{production_positive_rows} production positive row(s) "
             "present BUT no outcomes attached yet. Calibration "
             "remains explicitly NOT recommended until outcomes "
             "are collected via the shadow-outcome cycle."),
        )
    return (
        VERDICT_V327_OUTCOMES_NEEDED,
        (f"{production_positive_rows} production positive row(s) "
         "AND outcomes available. Operator may stage shadow-outcome "
         "calibration as the next reviewed step — calibration is "
         "NEVER auto-applied by this reporter."),
    )


def _classify_verdict(
    *,
    positive_rows: int,
    varying_components: int,
    min_positive_rows: int,
    min_varying_components: int,
) -> tuple[str, str]:
    if positive_rows == 0:
        return (
            VERDICT_NOT_READY,
            ("No entry-capable ledger row carries a non-null "
             "confidence_score yet. Verify Phase-2 wiring once monitors "
             "begin emitting positive-path rows."),
        )
    if positive_rows < min_positive_rows:
        return (
            VERDICT_NEEDS_CANDIDATES,
            (f"Only {positive_rows} positive row(s); "
             f"need >= {min_positive_rows} to begin pre-calibration."),
        )
    if varying_components < min_varying_components:
        return (
            VERDICT_NEEDS_VARIANCE,
            (f"{varying_components}/8 components show meaningful "
             f"variance; need >= {min_varying_components}."),
        )
    return (
        VERDICT_READY,
        ("Positive row count and component variance both clear the "
         "pre-calibration threshold. Operator may stage shadow-outcome "
         "calibration as the next reviewed step."),
    )


# ─── Build ────────────────────────────────────────────────────────────────────


def build_report(
    *,
    as_of: datetime,
    days: int = 7,
    base_dir: Path | None = None,
    min_positive_rows: int = DEFAULT_MIN_POSITIVE_ROWS,
    min_varying_components: int = DEFAULT_MIN_VARYING_COMPONENTS,
    variance_eps: float = DEFAULT_VARIANCE_EPSILON,
) -> dict[str, Any]:
    base = base_dir if base_dir is not None else LEDGER_DIR
    rows = _load_ledger_rows(as_of=as_of, days=days, base_dir=base)

    positive_rows = [r for r in rows
                     if r.get("confidence_score") is not None]
    scores = [float(r["confidence_score"]) for r in positive_rows]

    completeness_values: list[float] = []
    for r in positive_rows:
        val = r.get("builder_completeness")
        if val is None:
            # Fallback: nested under confidence_components meta key.
            comps = r.get("confidence_components") or {}
            if isinstance(comps, dict):
                val = comps.get("__completeness__")
        try:
            if val is not None:
                completeness_values.append(float(val))
        except (TypeError, ValueError):
            pass

    component_summary = _summarize_components(
        positive_rows, variance_eps=variance_eps)
    decision_counts = _decision_counts(positive_rows)

    verdict, verdict_reason = _classify_verdict(
        positive_rows=len(positive_rows),
        varying_components=component_summary["varying_components"],
        min_positive_rows=min_positive_rows,
        min_varying_components=min_varying_components,
    )

    # ─── v3.27 source-separation block ──────────────────────────────────
    fixture_only_rows = _count_fixture_only_rows(positive_rows)
    # Production positives must EXCLUDE any fixture-tagged rows.
    production_positive_rows = max(
        0, len(positive_rows) - fixture_only_rows)
    replay_positive_rows = _count_replay_positive_rows()
    near_miss_rows_count = _count_near_miss_rows(
        as_of=as_of, days=days)
    outcomes_available = _has_outcomes()

    verdict_v327, verdict_v327_reason = _classify_verdict_v327(
        production_positive_rows=production_positive_rows,
        replay_positive_rows=replay_positive_rows,
        near_miss_rows=near_miss_rows_count,
        has_outcomes=outcomes_available,
    )

    return {
        "version":           VERSION,
        "generated_at_iso":  datetime.now(timezone.utc).isoformat(),
        "as_of":             as_of.isoformat(),
        "git_head":          _git_head(),
        "window_days":       days,
        "rows_total":        len(rows),
        "positive_rows":     len(positive_rows),
        "score_summary":     _summarize_scores(scores),
        "completeness_summary": _summarize_completeness(
            completeness_values),
        "components":        component_summary,
        "decision_counts":   decision_counts,
        "params": {
            "min_positive_rows":       min_positive_rows,
            "min_varying_components":  min_varying_components,
            "variance_epsilon":        variance_eps,
        },
        "verdict":           verdict,
        "verdict_reason":    verdict_reason,
        # v3.27 extension — separation between sources.
        "source_separation": {
            "production_positive_rows": production_positive_rows,
            "replay_positive_rows":     replay_positive_rows,
            "near_miss_rows":           near_miss_rows_count,
            "fixture_only_rows":        fixture_only_rows,
            "outcomes_available":       outcomes_available,
            "verdict_v327":             verdict_v327,
            "verdict_v327_reason":      verdict_v327_reason,
            "note":                     (
                "Calibration is NEVER recommended without outcomes. "
                "Replay / near-miss / fixture rows NEVER count "
                "as production positives."
            ),
        },
        "standing_markers":  list(STANDING_MARKERS),
        "safety": {
            "edge_gate_enabled":          False,
            "allow_broker_paper":         False,
            "live_trading_supported":     False,
            "modifies_state_json":        False,
            "auto_adjusts_thresholds":    False,
            "imports_alpaca_orders":      False,
            "makes_network_calls":        False,
            "replay_counted_as_production":   False,
            "near_miss_counted_as_production": False,
            "fixture_counted_as_production":  False,
            "calibration_recommended_without_outcomes": False,
        },
    }


# ─── Rendering ────────────────────────────────────────────────────────────────


def render_md(rep: dict[str, Any]) -> str:
    standing = "\n".join(f"- `{m}`" for m in rep["standing_markers"])
    score = rep["score_summary"]
    comp = rep["components"]
    deci = rep["decision_counts"]

    component_rows = [
        "| Component | Samples | Min | Max | Mean | Variance | Varying |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, c in sorted(comp["per_component"].items()):
        component_rows.append(
            f"| `{name}` | {c['samples']} | {c['min']} | {c['max']} | "
            f"{c['mean']} | {c['variance']} | "
            f"{'yes' if c['varying'] else 'no'} |"
        )
    if len(component_rows) == 2:
        component_rows.append("| (none) | | | | | | |")

    decision_rows = [
        "| Decision | Count |",
        "|---|---|",
    ]
    for d in ("ALLOW", "ALERT_ONLY", "BLOCK", "ERROR"):
        decision_rows.append(f"| `{d}` | {deci.get(d, 0)} |")
    other = {k: v for k, v in deci.items()
             if k not in ("ALLOW", "ALERT_ONLY", "BLOCK", "ERROR")}
    for d, v in sorted(other.items()):
        decision_rows.append(f"| `{d}` | {v} |")

    sep = rep.get("source_separation", {})
    separation_table = "\n".join([
        "| Source | Count | Counts as production? |",
        "|---|---|---|",
        f"| PRODUCTION_POSITIVE_ROWS | `{sep.get('production_positive_rows', 0)}` | yes |",
        f"| REPLAY_POSITIVE_ROWS     | `{sep.get('replay_positive_rows', 0)}` | NO (review-only) |",
        f"| NEAR_MISS_ROWS           | `{sep.get('near_miss_rows', 0)}` | NO (advisory) |",
        f"| FIXTURE_ONLY_ROWS        | `{sep.get('fixture_only_rows', 0)}` | NO (test artefacts) |",
        f"| OUTCOMES_AVAILABLE       | `{sep.get('outcomes_available', False)}` | gate for calibration |",
    ])
    return f"""# Confidence Pre-Calibration Readiness ({rep["version"]})

**Generated:** `{rep["generated_at_iso"]}`
**As of:** `{rep["as_of"]}`
**Git HEAD:** `{rep["git_head"]}`
**Window:** last {rep["window_days"]} days
**Rows total:** `{rep["rows_total"]}`
**Positive rows (non-null confidence_score):** `{rep["positive_rows"]}`

## v3.27 Source separation

**Verdict (v3.27):** `{sep.get("verdict_v327", "unknown")}`

{sep.get("verdict_v327_reason", "")}

{separation_table}

> Calibration is **NEVER** recommended without real outcomes.
> Replay rows, near-miss rows, and fixture rows are surfaced for
> operator situational awareness only — they never count as
> production positives.

## Verdict (v3.26, retained for back-compat)

**`{rep["verdict"]}`**

{rep["verdict_reason"]}

## Confidence-score distribution

| Stat | Value |
|---|---|
| `count` | {score["count"]} |
| `min` | {score["min"]} |
| `median` | {score["median"]} |
| `p95` | {score["p95"]} |
| `max` | {score["max"]} |
| `mean` | {score["mean"]} |

## Builder completeness

| Stat | Value |
|---|---|
| `count` | {rep["completeness_summary"]["count"]} |
| `min` | {rep["completeness_summary"]["min"]} |
| `median` | {rep["completeness_summary"]["median"]} |
| `mean` | {rep["completeness_summary"]["mean"]} |

## Per-component variance

Total components observed: `{comp["total_components_seen"]}`
Varying components: `{comp["varying_components"]}`
Default-only components: `{comp["default_only_components"]}`

{chr(10).join(component_rows)}

## Confidence decision counts

{chr(10).join(decision_rows)}

## Thresholds used

| Param | Value |
|---|---|
| `min_positive_rows` | `{rep["params"]["min_positive_rows"]}` |
| `min_varying_components` | `{rep["params"]["min_varying_components"]}` |
| `variance_epsilon` | `{rep["params"]["variance_epsilon"]}` |

## Safety contract

- This reporter NEVER imports `alpaca_orders`.
- This reporter NEVER makes a network call.
- This reporter NEVER mutates strategy thresholds.
- Verdicts are descriptive — they do not gate execution.
- Pre-calibration outputs do NOT count as real-market evidence.

## Standing markers

{standing}
"""


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the v3.26 confidence pre-calibration "
                    "readiness report.")
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--min-positive-rows", type=int,
                          default=DEFAULT_MIN_POSITIVE_ROWS)
    parser.add_argument("--min-varying-components", type=int,
                          default=DEFAULT_MIN_VARYING_COMPONENTS)
    parser.add_argument("--variance-eps", type=float,
                          default=DEFAULT_VARIANCE_EPSILON)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    if args.as_of:
        try:
            as_of = datetime.fromisoformat(
                args.as_of.replace("Z", "+00:00"))
        except ValueError:
            print(f"Invalid --as-of: {args.as_of}", file=sys.stderr)
            return 2
    else:
        as_of = datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    rep = build_report(
        as_of=as_of,
        days=args.days,
        min_positive_rows=args.min_positive_rows,
        min_varying_components=args.min_varying_components,
        variance_eps=args.variance_eps,
    )
    md = render_md(rep)

    if args.json:
        print(json.dumps(rep, indent=2, sort_keys=True))

    if not args.no_write:
        LATEST_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_JSON_PATH.write_text(
            json.dumps(rep, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        LATEST_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_MD_PATH.write_text(md, encoding="utf-8")
        print(f"Wrote {LATEST_JSON_PATH.relative_to(REPO_ROOT)}")
        print(f"Wrote {LATEST_MD_PATH.relative_to(REPO_ROOT)}")
        print(f"Verdict: {rep['verdict']} "
              f"| positive_rows={rep['positive_rows']} "
              f"| varying_components="
              f"{rep['components']['varying_components']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
