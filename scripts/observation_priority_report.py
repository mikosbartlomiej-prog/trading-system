#!/usr/bin/env python3
"""v3.21.0 (2026-06-04) — Observation priority report.

Takes a triples file (JSON list) and writes per-triple priority scores
and a sorted markdown summary to
``reports/observation_priority/<date>.{jsonl,md}``.

The script is read-only with respect to trading. It NEVER mutates
runtime state, NEVER enables trading, NEVER bypasses risk gates. The
recommendations are consumed by the experiment scheduler, which itself
is observe-only.

USAGE
-----
    python3 scripts/observation_priority_report.py \
        --input shared/_examples/triples.json --date today

The input JSON must be a list of dicts compatible with
``shared.observation_priority.evaluate_triples``. If no input file is
provided the script writes an empty report so daily cron jobs can run
on a fresh repo without failing.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "shared"))

from observation_priority import (  # noqa: E402
    evaluate_triples,
    write_priority_jsonl,
    STATUS_PRIORITY_OBSERVE,
    STATUS_NORMAL_OBSERVE,
    STATUS_LOW_PRIORITY,
    STATUS_DO_NOT_OBSERVE,
    STATUS_NEEDS_DATA,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Score observation priority for a set of triples."
    )
    p.add_argument("--input", default=None,
                   help="JSON file with a list of triple dicts.")
    p.add_argument("--date", default="today",
                   help="UTC date YYYY-MM-DD or 'today'.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print summary to stdout; do not write files.")
    return p.parse_args()


def _resolve_date(value: str) -> str:
    if not value or value.lower() == "today":
        return datetime.now(timezone.utc).date().isoformat()
    return value


def _load_triples(path: Path | None) -> list[dict]:
    if path is None or not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    return []


def _render_summary(scores) -> str:
    counts = {
        STATUS_PRIORITY_OBSERVE: 0,
        STATUS_NORMAL_OBSERVE:   0,
        STATUS_LOW_PRIORITY:     0,
        STATUS_DO_NOT_OBSERVE:   0,
        STATUS_NEEDS_DATA:       0,
    }
    rows = []
    for s in scores:
        counts[s.status] = counts.get(s.status, 0) + 1
        rows.append((s.priority_score, s.strategy, s.symbol, s.regime, s.status))
    rows.sort(key=lambda r: (-r[0], r[1], r[2], r[3]))

    lines: list[str] = []
    lines.append("# Observation priority\n")
    lines.append(f"Triples scored: {len(scores)}\n")
    for status, n in counts.items():
        lines.append(f"- {status}: {n}\n")
    lines.append("\n## Sorted recommendations\n")
    lines.append("| score | strategy | symbol | regime | status |\n")
    lines.append("|---|---|---|---|---|\n")
    for score, strategy, symbol, regime, status in rows:
        lines.append(
            f"| {score:.3f} | {strategy} | {symbol} | {regime} | {status} |\n"
        )
    return "".join(lines)


def main() -> int:
    args = _parse_args()
    date_iso = _resolve_date(args.date)
    triples = _load_triples(Path(args.input) if args.input else None)
    scores = evaluate_triples(triples, emit_audit=not args.dry_run)

    summary = _render_summary(scores)
    if args.dry_run:
        sys.stdout.write(summary)
        return 0

    out_dir = _REPO_ROOT / "reports" / "observation_priority"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{date_iso}.md"
    md_path.write_text(summary, encoding="utf-8")
    write_priority_jsonl(scores, out_dir=out_dir, date_iso=date_iso)

    print(json.dumps({
        "date":      date_iso,
        "n_triples": len(scores),
        "md_path":   str(md_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
