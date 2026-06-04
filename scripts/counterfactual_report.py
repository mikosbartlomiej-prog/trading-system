#!/usr/bin/env python3
"""v3.20 ETAP 3 — CLI for the counterfactual outcome engine.

Reads ``learning-loop/opportunity_ledger/<date>.jsonl``, computes
counterfactual outcomes against bar data (via shared.market_data), and
prints a per-signal + per-gate summary. Audit lines are emitted with
``V320_COUNTERFACTUAL_COMPUTED``.

CRITICAL: counterfactual records are tagged
``evidence_source = "COUNTERFACTUAL"`` and NEVER merged into the paper
ledger. This script never places real orders.

Usage:
    python3 scripts/counterfactual_report.py --date 2026-06-03
    python3 scripts/counterfactual_report.py --date today --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

from counterfactual_outcomes import (  # noqa: E402
    DEFAULT_HORIZONS_HOURS,
    EVIDENCE_SOURCE_COUNTERFACTUAL,
    aggregate_by_gate,
    compute_counterfactuals,
    read_ledger,
)


def _resolve_date(arg: str) -> str:
    if arg.lower() in ("today", "now"):
        return datetime.now(timezone.utc).date().isoformat()
    return arg


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute counterfactual outcomes from opportunity ledger."
    )
    parser.add_argument("--date", default="today",
                        help="ISO date or 'today'. Default: today.")
    parser.add_argument("--horizons", type=str, default="24,48",
                        help="Comma-separated hours, e.g. '24,48'.")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON instead of human-readable text.")
    parser.add_argument("--no-audit", action="store_true",
                        help="Skip audit emission (offline use).")
    args = parser.parse_args()

    date_iso = _resolve_date(args.date)
    try:
        horizons = tuple(int(x.strip()) for x in args.horizons.split(",") if x.strip())
    except ValueError:
        horizons = DEFAULT_HORIZONS_HOURS

    signals = read_ledger(date_iso)
    results = compute_counterfactuals(
        signals,
        horizons_hours=horizons,
        emit_audit=not args.no_audit,
    )
    aggregates = aggregate_by_gate(results)

    if args.json:
        payload = {
            "date": date_iso,
            "evidence_source": EVIDENCE_SOURCE_COUNTERFACTUAL,
            "n_signals": len(signals),
            "horizons": list(horizons),
            "results": [r.to_dict() for r in results],
            "by_gate": [a.to_dict() for a in aggregates],
        }
        print(json.dumps(payload, indent=2, default=str))
        return 0

    print(f"=== Counterfactual report ({date_iso}) ===")
    print(f"Source: {EVIDENCE_SOURCE_COUNTERFACTUAL}   (never paper)")
    print(f"Signals scored: {len(signals)} across horizons {horizons}\n")

    if not results:
        print("No signals to score (ledger empty or missing).")
        return 0

    profitable = sum(1 for r in results if r.was_rejection_correct is False)
    correct = sum(1 for r in results if r.was_rejection_correct is True)
    unknown = sum(1 for r in results if r.was_rejection_correct is None)
    print(f"False rejections (would have profited): {profitable}")
    print(f"Correct rejections (would have lost / flat): {correct}")
    print(f"Unknown (bar data missing): {unknown}\n")

    print("Per-gate breakdown:")
    for agg in aggregates:
        print(f"  {agg.gate} @ {agg.horizon_hours}h: "
              f"rej={agg.n_rejections} "
              f"false={agg.n_false_rejections} "
              f"correct={agg.n_correct_rejections} "
              f"unknown={agg.n_unknown} "
              f"false_rate={agg.false_rejection_rate:.3f}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
