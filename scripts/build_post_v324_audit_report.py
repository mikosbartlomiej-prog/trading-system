#!/usr/bin/env python3
"""v3.25 — Post-v3.24 Production Audit Reporter.

Reads opportunity_ledger rows emitted AFTER the v3.24 push timestamp
and answers the central v3.25 question: did v3.24's enforcement
actually populate production rows with confidence?

The reporter classifies rows into entry-capable vs observe-only,
counts confidence_status distribution, and computes confidence
input completeness averages. Output is a JSON snapshot and a
Markdown report.

HARD SAFETY
-----------
- NEVER imports ``alpaca_orders``.
- NEVER calls submit_order / place_order / safe_close /
  place_stock_order / place_crypto_order / place_option_order /
  close_position / close_all_positions / any broker entry point.
- NEVER makes a network call. Pure local file I/O.
- Fail-soft on every read. Returns 0 even if no eligible rows
  exist.

Usage
-----
::

    python3 scripts/build_post_v324_audit_report.py
    python3 scripts/build_post_v324_audit_report.py --cutoff-iso 2026-06-15T11:35:05+00:00
    python3 scripts/build_post_v324_audit_report.py --json --no-write

Exit codes
----------
``0`` always. The script logs but does not raise.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "shared") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "shared"))


VERSION = "v3.25.0"
DEFAULT_CUTOFF_ISO = "2026-06-15T11:35:05+00:00"

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT_BY_REPORTER",
    "PURE_LOCAL_FILE_OPERATIONS",
    "NEAR_MISS_IS_NOT_TRADE_EVIDENCE",
    "SHADOW_IS_NOT_BROKER_PAPER",
    "LLM_ADVISORY_ONLY",
)


def _row_timestamp(r: dict) -> str:
    return (
        r.get("timestamp")
        or r.get("emit_timestamp")
        or r.get("written_iso")
        or ""
    )


def _is_entry_capable(r: dict) -> bool:
    """Determine entry-capable from row top-level or raw_signal nested."""
    if "entry_capable" in r and r["entry_capable"] is not None:
        return bool(r["entry_capable"])
    raw = r.get("raw_signal") or {}
    if isinstance(raw, dict):
        if "entry_capable" in raw and raw["entry_capable"] is not None:
            return bool(raw["entry_capable"])
        action = str(raw.get("action") or "").upper()
        state = str(raw.get("signal_state") or "").upper()
        if action in ("BUY", "SELL", "SELL_SHORT", "LONG", "SHORT"):
            return True
        if state in ("DETECTED", "EXECUTED", "BUY"):
            return True
    return False


def _confidence_status(r: dict) -> str:
    """Read confidence_status from top-level or raw_signal nested."""
    top = r.get("confidence_status")
    if top is not None:
        return str(top)
    raw = r.get("raw_signal") or {}
    if isinstance(raw, dict) and raw.get("confidence_status") is not None:
        return str(raw["confidence_status"])
    return "NULL"


def _confidence_decision(r: dict) -> str:
    top = r.get("confidence_decision")
    if top is not None:
        return str(top)
    raw = r.get("raw_signal") or {}
    if isinstance(raw, dict) and raw.get("confidence_decision") is not None:
        return str(raw["confidence_decision"])
    return "NULL"


def _completeness(r: dict) -> float | None:
    val = r.get("confidence_input_completeness")
    if val is None:
        raw = r.get("raw_signal") or {}
        val = raw.get("confidence_input_completeness") if isinstance(raw, dict) else None
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _has_default_reasons(r: dict) -> bool:
    top = r.get("confidence_default_reasons")
    if top:
        return True
    raw = r.get("raw_signal") or {}
    if isinstance(raw, dict):
        nested = raw.get("confidence_default_reasons")
        if nested:
            return True
    return False


def _source_monitor(r: dict) -> str:
    src = r.get("source_monitor")
    if src:
        return str(src)
    raw = r.get("raw_signal") or {}
    if isinstance(raw, dict) and raw.get("source_monitor"):
        return str(raw["source_monitor"])
    # Infer from strategy_id if monitor not set
    strat = r.get("strategy") or r.get("strategy_id") or ""
    if "crypto" in strat:
        return "crypto-monitor"
    if "options" in strat:
        return "options-monitor"
    return "unknown"


def _strategy_id(r: dict) -> str:
    return str(r.get("strategy") or r.get("strategy_id") or "unknown")


def load_rows(ledger_dir: Path, cutoff_iso: str, max_files: int = 7) -> dict:
    """Load rows from the most recent N ledger files, filter by cutoff."""
    files = sorted(ledger_dir.glob("*.jsonl"))[-max_files:]
    post_rows: list[dict] = []
    all_rows: list[dict] = []
    files_scanned: list[str] = []
    for f in files:
        files_scanned.append(f.name)
        try:
            with open(f) as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    all_rows.append(r)
                    if _row_timestamp(r) >= cutoff_iso:
                        post_rows.append(r)
        except OSError:
            continue
    return {
        "files_scanned": files_scanned,
        "all_rows": all_rows,
        "post_rows": post_rows,
    }


def compute_audit(rows: list[dict], cutoff_iso: str, used_fallback: bool) -> dict:
    """Compute the full audit summary from a list of rows."""
    n = len(rows)
    entry_capable_rows = [r for r in rows if _is_entry_capable(r)]
    observe_only_rows = [r for r in rows if not _is_entry_capable(r)]

    score_pop = sum(1 for r in rows if r.get("confidence_score") is not None)
    comp_pop = sum(1 for r in rows if (r.get("confidence_components") or {}))
    drp_pop = sum(1 for r in rows if _has_default_reasons(r))

    status_dist: Counter = Counter()
    for r in rows:
        status_dist[_confidence_status(r)] += 1

    decision_dist: Counter = Counter()
    for r in rows:
        decision_dist[_confidence_decision(r)] += 1

    completeness_vals: list[float] = []
    for r in rows:
        c = _completeness(r)
        if c is not None:
            completeness_vals.append(c)
    avg_completeness = (
        sum(completeness_vals) / len(completeness_vals)
        if completeness_vals else None
    )

    src_dist: Counter = Counter(_source_monitor(r) for r in rows)
    strat_dist: Counter = Counter(_strategy_id(r) for r in rows)
    risk_dist: Counter = Counter(str(r.get("risk_decision") or "NULL") for r in rows)

    # Entry-capable confidence-bearing count: a row is "confidence-bearing"
    # iff confidence_score is non-null OR confidence_status is ERROR (the
    # explicit failure sentinel introduced by v3.24).
    ec_n = len(entry_capable_rows)
    ec_with_score = sum(
        1 for r in entry_capable_rows if r.get("confidence_score") is not None
    )
    ec_with_error = sum(
        1 for r in entry_capable_rows if _confidence_status(r) == "ERROR"
    )
    ec_bearing = ec_with_score + ec_with_error
    ec_silent_null = ec_n - ec_bearing

    # Evidence quality score (if shared.evidence_quality is importable).
    eq_avg: float | None = None
    eq_count = 0
    try:
        from evidence_quality import score_row  # type: ignore
        scores: list[float] = []
        for r in rows:
            try:
                s = score_row(r)
                val = getattr(s, "score", None)
                if val is None and isinstance(s, (int, float)):
                    val = float(s)
                if val is not None:
                    scores.append(float(val))
            except Exception:
                continue
        if scores:
            eq_avg = sum(scores) / len(scores)
            eq_count = len(scores)
    except Exception:
        pass

    # Verdict logic.
    if used_fallback or n == 0:
        verdict = "NO_ROWS_TO_AUDIT"
    elif ec_n == 0:
        verdict = "NO_BUT_CRON_HASNT_FIRED_YET"
    elif ec_silent_null > 0 and ec_bearing == 0:
        verdict = "NO_RUNTIME_LEAK"
    elif ec_silent_null == 0:
        verdict = "YES_FULLY"
    else:
        verdict = "YES_PARTIAL"

    top_monitor = src_dist.most_common(1)[0][0] if src_dist else None
    top_strategy = strat_dist.most_common(1)[0][0] if strat_dist else None

    return {
        "version":                       VERSION,
        "cutoff_iso":                    cutoff_iso,
        "used_fallback_to_recent_rows":  used_fallback,
        "rows_total":                    n,
        "entry_capable":                 ec_n,
        "observe_only":                  len(observe_only_rows),
        "confidence_score_populated":    score_pop,
        "confidence_score_populated_pct": (
            round(100.0 * score_pop / n, 2) if n else 0.0
        ),
        "confidence_components_nonempty": comp_pop,
        "confidence_components_nonempty_pct": (
            round(100.0 * comp_pop / n, 2) if n else 0.0
        ),
        "confidence_status_distribution": dict(status_dist),
        "confidence_decision_distribution": dict(decision_dist),
        "confidence_default_reasons_populated": drp_pop,
        "confidence_input_completeness_avg": avg_completeness,
        "by_source_monitor":             dict(src_dist),
        "by_strategy_id":                dict(strat_dist),
        "by_risk_decision":              dict(risk_dist),
        "entry_capable_with_score":      ec_with_score,
        "entry_capable_with_error":      ec_with_error,
        "entry_capable_confidence_bearing": ec_bearing,
        "entry_capable_silent_null":     ec_silent_null,
        "evidence_quality_score_avg":    eq_avg,
        "evidence_quality_rows_scored":  eq_count,
        "top_source_monitor":            top_monitor,
        "top_strategy_id":               top_strategy,
        "verdict":                       verdict,
        "standing_markers":              list(STANDING_MARKERS),
        "generated_at":                  datetime.now(timezone.utc).isoformat(),
    }


def render_markdown(summary: dict) -> str:
    lines: list[str] = []
    lines.append(f"# Post-v3.24 Production Audit ({summary['version']})")
    lines.append("")
    lines.append(f"Generated: {summary['generated_at']}")
    lines.append(f"Cutoff: `{summary['cutoff_iso']}`")
    if summary["used_fallback_to_recent_rows"]:
        lines.append("")
        lines.append("> ⚠ No rows existed after the v3.24 push cutoff.")
        lines.append("> This report is empty by design.")
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    lines.append(f"**{summary['verdict']}**")
    lines.append("")
    lines.append("## Row counts")
    lines.append("")
    lines.append(f"- Total rows audited: {summary['rows_total']}")
    lines.append(f"- Entry-capable: {summary['entry_capable']}")
    lines.append(f"- Observe-only: {summary['observe_only']}")
    lines.append("")
    lines.append("## Confidence presence")
    lines.append("")
    lines.append(
        f"- confidence_score populated: {summary['confidence_score_populated']}"
        f" ({summary['confidence_score_populated_pct']}%)"
    )
    lines.append(
        f"- confidence_components non-empty: "
        f"{summary['confidence_components_nonempty']}"
        f" ({summary['confidence_components_nonempty_pct']}%)"
    )
    lines.append(
        f"- confidence_default_reasons populated: "
        f"{summary['confidence_default_reasons_populated']}"
    )
    avg = summary["confidence_input_completeness_avg"]
    lines.append(
        f"- confidence_input_completeness avg: "
        f"{avg if avg is not None else 'n/a'}"
    )
    lines.append("")
    lines.append("## Entry-capable confidence-bearing slice")
    lines.append("")
    lines.append(f"- with numeric score: {summary['entry_capable_with_score']}")
    lines.append(f"- with ERROR status: {summary['entry_capable_with_error']}")
    lines.append(
        f"- bearing (score or ERROR): "
        f"{summary['entry_capable_confidence_bearing']}"
    )
    lines.append(
        f"- silent-null (v3.24 contract violation): "
        f"{summary['entry_capable_silent_null']}"
    )
    lines.append("")
    lines.append("## Distributions")
    lines.append("")
    lines.append("### confidence_status")
    for k, v in sorted(summary["confidence_status_distribution"].items()):
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("### confidence_decision")
    for k, v in sorted(summary["confidence_decision_distribution"].items()):
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("### by source_monitor")
    for k, v in sorted(summary["by_source_monitor"].items()):
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("### by strategy_id")
    for k, v in sorted(summary["by_strategy_id"].items()):
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("### by risk_decision")
    for k, v in sorted(summary["by_risk_decision"].items()):
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Evidence quality")
    lines.append("")
    eq_avg = summary["evidence_quality_score_avg"]
    lines.append(
        f"- avg score: {eq_avg if eq_avg is not None else 'n/a'} "
        f"({summary['evidence_quality_rows_scored']} rows scored)"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Standing markers")
    lines.append("")
    for m in summary["standing_markers"]:
        lines.append(f"- `{m}`")
    lines.append("")
    return "\n".join(lines)


def write_outputs(summary: dict, repo_root: Path) -> dict:
    json_path = (
        repo_root / "learning-loop" / "shadow_evidence"
        / "post_v324_audit_latest.json"
    )
    md_path = repo_root / "docs" / "POST_V324_PRODUCTION_AUDIT.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True))
    md_path.write_text(render_markdown(summary))
    return {"json_path": str(json_path), "md_path": str(md_path)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--cutoff-iso", default=DEFAULT_CUTOFF_ISO,
        help="Only count rows with timestamp >= this ISO-8601 instant.",
    )
    p.add_argument(
        "--as-of", default=None,
        help="Stamp the generated_at field to this ISO-8601 (else now).",
    )
    p.add_argument(
        "--ledger-dir",
        default=str(REPO_ROOT / "learning-loop" / "opportunity_ledger"),
    )
    p.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    p.add_argument(
        "--no-write", action="store_true",
        help="Do not write to disk; just print.",
    )
    args = p.parse_args(argv)

    ledger_dir = Path(args.ledger_dir)
    loaded = load_rows(ledger_dir, args.cutoff_iso, max_files=7)
    post_rows = loaded["post_rows"]
    used_fallback = False
    if not post_rows:
        # Fallback: most recent rows regardless of cutoff so the report
        # is never empty. The flag is surfaced in the summary.
        used_fallback = True
        post_rows = loaded["all_rows"][-200:]

    summary = compute_audit(
        post_rows, args.cutoff_iso, used_fallback=used_fallback
    )
    if args.as_of:
        summary["generated_at"] = args.as_of
    summary["files_scanned"] = loaded["files_scanned"]

    if not args.no_write:
        paths = write_outputs(summary, REPO_ROOT)
        summary["_paths"] = paths
        print(f"Wrote {paths['json_path']}")
        print(f"Wrote {paths['md_path']}")

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(
            f"verdict={summary['verdict']} rows={summary['rows_total']} "
            f"entry_capable={summary['entry_capable']} "
            f"score_pop={summary['confidence_score_populated']} "
            f"silent_null={summary['entry_capable_silent_null']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
