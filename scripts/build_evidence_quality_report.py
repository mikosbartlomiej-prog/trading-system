#!/usr/bin/env python3
"""v3.24 ETAP 11 — Evidence quality reporter.

Reads the last 7 days of the signal opportunity ledger, scores every
row via :func:`shared.evidence_quality.score_row`, and emits both a
machine-readable JSON summary (``learning-loop/evidence_quality_latest.json``)
and a human-readable Markdown report (``docs/EVIDENCE_QUALITY_STATUS.md``).

HARD SAFETY
-----------
- NEVER imports ``alpaca_orders``.
- NEVER places orders. NEVER calls a broker.
- NEVER makes a network call. Pure local-filesystem read + write.
- The reporter is advisory; the labels it emits do NOT, by themselves,
  authorise a trade. EDGE_GATE_ENABLED and ALLOW_BROKER_PAPER remain
  false.

Usage
-----
::

    python3 scripts/build_evidence_quality_report.py
    python3 scripts/build_evidence_quality_report.py --days 14
    python3 scripts/build_evidence_quality_report.py --ledger-dir /tmp/ledger

Exit codes
----------
``0`` always (fail-soft). The script logs but does not raise on
missing files, malformed JSONL lines, or empty windows.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

# Make sibling imports work whether invoked as a module or a script.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "shared") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "shared"))

from evidence_quality import (  # type: ignore  # noqa: E402
    ALL_LABELS,
    LABEL_GARBAGE,
    LABEL_HIGH_QUALITY,
    LABEL_MARGINAL,
    LABEL_USABLE,
    EvidenceQualityScore,
    score_row,
)


# ─── Standing markers (re-asserted in every report) ───────────────


STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT_BY_REPORTER",
    "PURE_LOCAL_FILE_OPERATIONS",
)


# ─── Ledger reading ────────────────────────────────────────────────


def _utc_today() -> datetime:
    return datetime.now(timezone.utc)


def _iter_ledger_files(ledger_dir: Path, days: int) -> Iterable[Path]:
    today = _utc_today().date()
    for i in range(days):
        d = (today - timedelta(days=i)).isoformat()
        p = ledger_dir / f"{d}.jsonl"
        if p.exists():
            yield p


def _iter_rows(ledger_dir: Path, days: int) -> Iterable[dict]:
    for path in _iter_ledger_files(ledger_dir, days):
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        # Fail-soft: skip malformed line.
                        continue
                    if isinstance(obj, dict):
                        yield obj
        except OSError:
            # Fail-soft: skip unreadable file.
            continue


# ─── Aggregation ───────────────────────────────────────────────────


def aggregate(
    scores: Iterable[EvidenceQualityScore],
    rows:   Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compute label distribution, per-monitor + per-strategy averages.

    ``scores`` and ``rows`` must be the same length and aligned. We
    accept them as separate iterables so callers can choose to stream
    or to materialise.
    """
    label_counts: dict[str, int] = {label: 0 for label in ALL_LABELS}
    total_score = 0
    n = 0

    per_monitor:  dict[str, list[int]] = defaultdict(list)
    per_strategy: dict[str, list[int]] = defaultdict(list)

    for s, row in zip(scores, rows):
        n += 1
        total_score += s.score
        label_counts[s.label] = label_counts.get(s.label, 0) + 1

        raw = row.get("raw_signal") if isinstance(row, Mapping) else {}
        if not isinstance(raw, Mapping):
            raw = {}

        monitor = (row.get("source_monitor")
                   if isinstance(row, Mapping) else None)
        if not monitor:
            monitor = raw.get("source_monitor")
        if not monitor:
            monitor = "(unknown)"

        strategy = (row.get("strategy_id") or row.get("strategy")
                    if isinstance(row, Mapping) else None)
        if not strategy:
            strategy = raw.get("strategy_id") or raw.get("strategy")
        if not strategy:
            strategy = "(unknown)"

        per_monitor[str(monitor)].append(s.score)
        per_strategy[str(strategy)].append(s.score)

    avg = (total_score / n) if n else 0.0

    return {
        "rows_scored":         n,
        "average_score":       round(avg, 2),
        "label_distribution":  label_counts,
        "label_distribution_pct": {
            k: round(v * 100.0 / max(n, 1), 2)
            for k, v in label_counts.items()
        },
        "per_monitor_average": {
            k: round(sum(v) / max(len(v), 1), 2)
            for k, v in per_monitor.items()
        },
        "per_monitor_count": {k: len(v) for k, v in per_monitor.items()},
        "per_strategy_average": {
            k: round(sum(v) / max(len(v), 1), 2)
            for k, v in per_strategy.items()
        },
        "per_strategy_count": {k: len(v) for k, v in per_strategy.items()},
    }


# ─── Rendering ─────────────────────────────────────────────────────


def _render_markdown(summary: dict[str, Any], days: int) -> str:
    lines: list[str] = []
    ts = _utc_today().isoformat(timespec="seconds")
    lines.append(f"# Evidence quality status — {ts}")
    lines.append("")
    lines.append(f"Window: last **{days} days** of opportunity ledger.")
    lines.append(f"Rows scored: **{summary['rows_scored']}**")
    lines.append(f"Average score: **{summary['average_score']} / 100**")
    lines.append("")
    lines.append("## Label distribution")
    lines.append("")
    lines.append("| Label | Count | % |")
    lines.append("|---|---:|---:|")
    for label in (LABEL_HIGH_QUALITY, LABEL_USABLE, LABEL_MARGINAL, LABEL_GARBAGE):
        cnt = summary["label_distribution"].get(label, 0)
        pct = summary["label_distribution_pct"].get(label, 0.0)
        lines.append(f"| {label} | {cnt} | {pct}% |")
    lines.append("")
    lines.append("## Per-monitor average")
    lines.append("")
    lines.append("| Monitor | Rows | Avg score |")
    lines.append("|---|---:|---:|")
    items = sorted(
        summary["per_monitor_average"].items(),
        key=lambda kv: kv[1],
        reverse=True,
    )
    for mon, avg in items:
        cnt = summary["per_monitor_count"].get(mon, 0)
        lines.append(f"| {mon} | {cnt} | {avg} |")
    lines.append("")
    lines.append("## Per-strategy average")
    lines.append("")
    lines.append("| Strategy | Rows | Avg score |")
    lines.append("|---|---:|---:|")
    items = sorted(
        summary["per_strategy_average"].items(),
        key=lambda kv: kv[1],
        reverse=True,
    )
    for strat, avg in items:
        cnt = summary["per_strategy_count"].get(strat, 0)
        lines.append(f"| {strat} | {cnt} | {avg} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("**Standing safety markers (re-asserted):**")
    for m in STANDING_MARKERS:
        lines.append(f"- `{m}`")
    lines.append("")
    return "\n".join(lines) + "\n"


# ─── Main ──────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--days", type=int, default=7,
        help="Number of days back to scan (default: 7).")
    ap.add_argument(
        "--ledger-dir", type=str, default=None,
        help=("Override the opportunity_ledger directory. Defaults to "
              "learning-loop/opportunity_ledger under the repo root."))
    ap.add_argument(
        "--json-out", type=str, default=None,
        help=("Override the JSON output path. Defaults to "
              "learning-loop/evidence_quality_latest.json."))
    ap.add_argument(
        "--md-out", type=str, default=None,
        help=("Override the Markdown output path. Defaults to "
              "docs/EVIDENCE_QUALITY_STATUS.md."))
    args = ap.parse_args(argv)

    ledger_dir = Path(
        args.ledger_dir
        or (REPO_ROOT / "learning-loop" / "opportunity_ledger"))
    json_out = Path(
        args.json_out
        or (REPO_ROOT / "learning-loop" / "evidence_quality_latest.json"))
    md_out = Path(
        args.md_out
        or (REPO_ROOT / "docs" / "EVIDENCE_QUALITY_STATUS.md"))

    # First pass: collect rows, second pass: score them. We collect
    # twice via materialisation so aggregate() can zip them aligned.
    rows = list(_iter_rows(ledger_dir, args.days))
    scores = [score_row(r) for r in rows]
    summary = aggregate(scores, rows)
    summary["window_days"]    = args.days
    summary["ledger_dir"]     = str(ledger_dir)
    summary["generated_at"]   = _utc_today().isoformat(timespec="seconds")
    summary["standing_markers"] = list(STANDING_MARKERS)

    try:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        with json_out.open("w", encoding="utf-8") as fh:
            json.dump(summary, fh, sort_keys=True, indent=2)
    except OSError as e:
        print(f"  [evidence-quality-report] JSON write failed: {e}",
              file=sys.stderr)

    try:
        md_out.parent.mkdir(parents=True, exist_ok=True)
        with md_out.open("w", encoding="utf-8") as fh:
            fh.write(_render_markdown(summary, args.days))
    except OSError as e:
        print(f"  [evidence-quality-report] MD write failed: {e}",
              file=sys.stderr)

    print(f"[evidence-quality-report] rows={summary['rows_scored']} "
          f"avg={summary['average_score']} "
          f"labels={summary['label_distribution']}")
    print(f"[evidence-quality-report] json→{json_out}")
    print(f"[evidence-quality-report] md→{md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
