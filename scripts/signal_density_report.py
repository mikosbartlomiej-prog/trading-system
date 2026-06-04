#!/usr/bin/env python3
"""v3.21 ETAP 4 — CLI for ``shared/signal_density_audit.py``.

Read-only classifier — labels each strategy with one of the
``DENSITY_STATUSES`` based on the last ``--days`` of evidence. Emits a
``V321_SIGNAL_DENSITY_AUDIT`` audit line per strategy unless
``--no-audit`` is supplied.

Never places orders. Never mutates state. Never flips
``EDGE_GATE_ENABLED``. Audit board reviews labels — this script does
not act on them.

Usage::

    python3 scripts/signal_density_report.py
    python3 scripts/signal_density_report.py --days 30 --json
    python3 scripts/signal_density_report.py --strategy momentum-long --no-audit
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))

from signal_density_audit import (  # noqa: E402
    run_density_audit,
)


def _render_human(report) -> str:
    lines: list[str] = []
    lines.append(
        f"=== Signal Density Audit ({report.window_days}d window) ==="
    )
    lines.append(
        f"Generated at: {report.generated_at.isoformat()}"
    )
    lines.append(
        f"Strategies scanned: {len(report.records)}"
    )
    lines.append("")
    if not report.records:
        lines.append("No strategy activity in window.")
        return "\n".join(lines)

    by_status: dict[str, list[str]] = {}
    for name, rec in report.records.items():
        by_status.setdefault(rec.status, []).append(name)

    lines.append("Status breakdown:")
    for status in sorted(by_status.keys()):
        names = sorted(by_status[status])
        lines.append(f"  {status}: {len(names)}")
        for n in names:
            r = report.records[n]
            lines.append(
                f"    - {n} (raw={r.raw_signal_count} "
                f"acc={r.accepted_count} rej={r.rejected_count} "
                f"shadow={r.shadow_paper_fills} "
                f"broker={r.broker_paper_fills} "
                f"symbols={r.symbol_coverage} "
                f"regimes={r.regime_coverage} "
                f"avg_conf={r.avg_confidence_score:.3f})"
            )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Signal Density Audit — read-only classifier that labels "
            "each strategy as DEAD / TOO_SPARSE / NOISY / "
            "HIGH_REJECTION_BUT_PROMISING / NEEDS_VARIANT_DISCOVERY / "
            "NEEDS_UNIVERSE_EXPANSION / HEALTHY_DENSITY."
        )
    )
    parser.add_argument(
        "--days", type=int, default=14,
        help="Window size in days (default: 14).",
    )
    parser.add_argument(
        "--strategy", type=str, default=None,
        help="Filter to a single strategy name.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of human-readable text.",
    )
    parser.add_argument(
        "--no-audit", action="store_true",
        help="Skip writing V321_SIGNAL_DENSITY_AUDIT lines.",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    report = run_density_audit(
        now=now, days_window=args.days, emit_audit=not args.no_audit
    )

    if args.strategy:
        if args.strategy in report.records:
            report.records = {
                args.strategy: report.records[args.strategy]
            }
        else:
            report.records = {}

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
        return 0
    print(_render_human(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
