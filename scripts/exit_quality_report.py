#!/usr/bin/env python3
"""v3.20.0 (2026-06-04) — Exit Quality report (ETAP 8).

Reads the paper / shadow ledger via `shared.exit_quality`, computes
per-trade post-mortem fields, aggregates per strategy / symbol / regime
/ confidence_bucket, and renders a Markdown report to:

    docs/exit_quality_LATEST.md       (paper, default)
    docs/exit_quality_BACKTEST_LATEST.md   (--source backtest)
    docs/exit_quality_REPLAY_LATEST.md     (--source replay)

NEVER calls the broker. NEVER calls a paid API. NEVER mutates state.
NEVER auto-disables anything. Recommendations in the report are STRINGS
ONLY — topics for the operator to review.

Exits 0 even when the ledger is empty (nothing to triage yet ≠ failure).

Usage:
    python3 scripts/exit_quality_report.py
    python3 scripts/exit_quality_report.py --window-days 90
    python3 scripts/exit_quality_report.py --source backtest
    python3 scripts/exit_quality_report.py --out-dir /tmp/reports
    python3 scripts/exit_quality_report.py --json   # stdout JSON for piping
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "shared"))

from exit_quality import analyse_ledger, render_report  # type: ignore  # noqa: E402
from evidence_source import EvidenceSource  # type: ignore  # noqa: E402


_SOURCE_MAP = {
    "paper":    EvidenceSource.PAPER,
    "backtest": EvidenceSource.BACKTEST,
    "replay":   EvidenceSource.REPLAY,
}


def _out_filename(source: EvidenceSource) -> str:
    sv = source.value if hasattr(source, "value") else str(source).upper()
    if sv == "PAPER":
        return "exit_quality_LATEST.md"
    return f"exit_quality_{sv}_LATEST.md"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--window-days", type=int, default=180,
                    help="Look-back window in days (default 180)")
    p.add_argument("--source", choices=sorted(_SOURCE_MAP.keys()),
                    default="paper",
                    help="Ledger to read from. paper / backtest / replay.")
    p.add_argument("--out-dir", type=str, default=str(_REPO_ROOT / "docs"),
                    help="Where to write the Markdown report.")
    p.add_argument("--json", action="store_true",
                    help="Print the result dict as JSON to stdout instead "
                         "of writing Markdown.")
    args = p.parse_args()

    source = _SOURCE_MAP[args.source]
    window_days = max(1, int(args.window_days))

    result = analyse_ledger(window_days=window_days, source=source)

    if args.json:
        sys.stdout.write(json.dumps(result, sort_keys=True,
                                     default=str, indent=2) + "\n")
        return 0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / _out_filename(source)
    out_path.write_text(render_report(result), encoding="utf-8")

    print(f"Wrote {out_path}")
    print(
        f"  source={source.value if hasattr(source, 'value') else source}, "
        f"window_days={window_days}, "
        f"trades={len(result.get('trades') or [])}, "
        f"recommendations={len(result.get('recommendations') or [])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
