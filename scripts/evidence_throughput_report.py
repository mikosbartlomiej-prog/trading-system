#!/usr/bin/env python3
"""v3.21 ETAP 1 — CLI for ``shared/evidence_throughput.py``.

Aggregates the four evidence sources (opportunity ledger, shadow
ledger, paper experiments, counterfactual audit) over a sliding
window and prints a per-strategy throughput report.

Read-only. Never places orders. Never mutates state. Honors the
evidence-source separation invariant — SHADOW / COUNTERFACTUAL /
BACKTEST / REPLAY counters are reported distinctly from BROKER_PAPER.

Usage::

    python3 scripts/evidence_throughput_report.py
    python3 scripts/evidence_throughput_report.py --days 30 --json
    python3 scripts/evidence_throughput_report.py --strategy momentum-long
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

from evidence_throughput import (  # noqa: E402
    DEFAULT_WINDOW_DAYS,
    compute_throughput,
)


def _render_human(report) -> str:
    lines: list[str] = []
    lines.append(
        f"=== Evidence Throughput ({report.window_days}d window) ==="
    )
    lines.append(
        f"Window: {report.window_start.isoformat()} "
        f"-> {report.window_end.isoformat()}"
    )
    lines.append("")
    lines.append(
        f"Raw signals:       {report.raw_signal_total}"
    )
    lines.append(
        f"Shadow fills:      {report.shadow_total}"
    )
    lines.append(
        f"Broker paper:      {report.broker_total}"
    )
    lines.append(
        f"Counterfactual:    {report.counterfactual_total} "
        f"(unknown: {report.unknown_total})"
    )
    lines.append("")
    if not report.strategies:
        lines.append("No strategy activity in window.")
        return "\n".join(lines)

    lines.append("Per-strategy breakdown:")
    width = max(len(s) for s in report.strategies.keys())
    header = (
        f"  {'strategy'.ljust(width)}  raw  acc  rej  obs  "
        f"shadow  broker  cf  status"
    )
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))
    for name in sorted(report.strategies.keys()):
        s = report.strategies[name]
        lines.append(
            f"  {name.ljust(width)}  "
            f"{s.raw_signals_count:>3}  "
            f"{s.accepted_count:>3}  "
            f"{s.rejected_count:>3}  "
            f"{s.observe_only_count:>3}  "
            f"{s.shadow_paper_fills:>6}  "
            f"{s.broker_paper_fills:>6}  "
            f"{s.counterfactual_outcomes:>2}  "
            f"{s.status}"
        )
        if s.estimated_days_to_n50 is not None:
            lines.append(
                f"      growth={s.broker_growth_rate:.2f}/d  "
                f"days_to_n50={s.estimated_days_to_n50}  "
                f"symbols={s.symbol_coverage}  "
                f"regimes={s.regime_coverage}"
            )
        else:
            lines.append(
                f"      growth={s.broker_growth_rate:.2f}/d  "
                f"days_to_n50=N/A  "
                f"symbols={s.symbol_coverage}  "
                f"regimes={s.regime_coverage}"
            )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evidence Throughput Monitor — read-only audit of how fast "
            "paper / shadow / counterfactual evidence is accumulating "
            "per strategy."
        )
    )
    parser.add_argument(
        "--days", type=int, default=DEFAULT_WINDOW_DAYS,
        help=f"Window size in days (default: {DEFAULT_WINDOW_DAYS}).",
    )
    parser.add_argument(
        "--strategy", type=str, default=None,
        help="Filter to a single strategy name.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of human-readable text.",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    report = compute_throughput(now=now, days_window=args.days)

    if args.strategy:
        if args.strategy in report.strategies:
            filtered = {args.strategy: report.strategies[args.strategy]}
        else:
            filtered = {}
        report.strategies = filtered

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
        return 0
    print(_render_human(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
