#!/usr/bin/env python3
"""v3.21.0 (2026-06-04) — Multi-horizon outcome report.

Reads the day's opportunity ledger, runs the multi-horizon outcome
engine, and writes a JSONL + markdown report under
``reports/multi_horizon_outcomes/<date>.{jsonl,md}``.

USAGE
-----
    python3 scripts/multi_horizon_outcome_report.py --date 2026-06-04
    python3 scripts/multi_horizon_outcome_report.py --date today --dry-run

This script is read-only with respect to the broker and never places
trades. It is governed by the Multi-Agent Audit Board: the operator
reviews the markdown output before any downstream gate is touched.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Resolve the repo root regardless of where we are invoked from.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "shared"))

from multi_horizon_outcomes import (  # noqa: E402
    HORIZONS,
    compute_outcomes_for_ledger,
    write_outcomes_jsonl,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Compute multi-horizon outcomes for one day of ledger."
    )
    p.add_argument("--date", default="today",
                   help="UTC date in YYYY-MM-DD or 'today'.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print summary; do not write any JSONL.")
    p.add_argument("--ledger-dir", default=None,
                   help="Override opportunity ledger directory.")
    return p.parse_args()


def _resolve_date(value: str) -> str:
    if not value or value.lower() == "today":
        return datetime.now(timezone.utc).date().isoformat()
    return value


def _render_summary(records: list[dict]) -> str:
    lines: list[str] = []
    lines.append("# Multi-horizon outcomes\n")
    lines.append(f"Signals: {len(records)}\n")
    if not records:
        lines.append("No opportunity-ledger entries for this date.\n")
        return "\n".join(lines)
    for horizon in HORIZONS:
        n_profitable = n_losing = n_flat = n_unknown = 0
        for rec in records:
            outcomes = rec.get("outcomes_by_horizon") or {}
            outcome = (outcomes.get(horizon) or {}).get("outcome")
            if outcome == "PROFITABLE":
                n_profitable += 1
            elif outcome == "LOSING":
                n_losing += 1
            elif outcome == "FLAT":
                n_flat += 1
            else:
                n_unknown += 1
        lines.append(
            f"## {horizon}\n"
            f"- profitable={n_profitable}\n"
            f"- losing={n_losing}\n"
            f"- flat={n_flat}\n"
            f"- unknown={n_unknown}\n"
        )
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    date_iso = _resolve_date(args.date)
    ledger_dir = Path(args.ledger_dir) if args.ledger_dir else None
    records = compute_outcomes_for_ledger(date_iso, ledger_dir=ledger_dir)

    summary = _render_summary(records)
    if args.dry_run:
        sys.stdout.write(summary)
        return 0

    out_dir = _REPO_ROOT / "reports" / "multi_horizon_outcomes"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{date_iso}.md"
    md_path.write_text(summary, encoding="utf-8")

    # Append per-horizon JSONL via the shared writer for audit parity
    # with the on-disk evidence path.
    write_outcomes_jsonl(records, out_dir=out_dir, date_iso=date_iso)

    print(json.dumps({
        "date":      date_iso,
        "n_signals": len(records),
        "md_path":   str(md_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
