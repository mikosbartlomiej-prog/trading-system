#!/usr/bin/env python3
"""v3.20 ETAP 9 — CLI for the gate calibration report.

Reads the opportunity ledger for ``--date``, computes counterfactual
outcomes, optionally merges executed paper trades from a JSON file,
and prints the per-gate calibration table.

Risk gate invariant: false rejections on the risk gate are reported
as ``safety_correct_rejection``, never as ``trading_opportunity_miss``.
The script will refuse to print "weaken risk gate" suggestions.

Usage:
    python3 scripts/gate_calibration_report.py --date 2026-06-03
    python3 scripts/gate_calibration_report.py --date today --json
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
    compute_counterfactuals,
    read_ledger,
)
from gate_calibration import (  # noqa: E402
    RISK_GATE_PROTECTED,
    build_calibration_report,
)


def _resolve_date(arg: str) -> str:
    if arg.lower() in ("today", "now"):
        return datetime.now(timezone.utc).date().isoformat()
    return arg


def _load_executed(path: str | None) -> list[dict]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict) and isinstance(data.get("trades"), list):
        return [d for d in data["trades"] if isinstance(d, dict)]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Per-gate calibration report (counterfactual + executed)."
    )
    parser.add_argument("--date", default="today")
    parser.add_argument("--horizon", type=int, default=24,
                        help="Horizon hours used for calibration table.")
    parser.add_argument("--executed",
                        help="Path to JSON file with executed paper trades.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-audit", action="store_true")
    args = parser.parse_args()

    date_iso = _resolve_date(args.date)
    horizon = args.horizon
    horizons = sorted(set([horizon, *DEFAULT_HORIZONS_HOURS]))

    signals = read_ledger(date_iso)
    counterfactuals = compute_counterfactuals(
        signals,
        horizons_hours=horizons,
        emit_audit=not args.no_audit,
    )
    executed_trades = _load_executed(args.executed)

    report = build_calibration_report(
        counterfactuals=counterfactuals,
        executed_trades=executed_trades,
        horizon_hours=horizon,
        emit_audit=not args.no_audit,
    )

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
        return 0

    print(f"=== Gate calibration report ({date_iso}, horizon={horizon}h) ===")
    print(f"Generated: {report.generated_at}\n")
    print(f"{'gate':16} {'acc_good':>9} {'acc_bad':>8} "
          f"{'rej_bad':>8} {'rej_good':>8} {'false_rate':>10} "
          f"{'protect':>8} {'miss':>8} {'net':>8}")
    for g in report.gates:
        miss_label = "safety" if g.gate.lower() in RISK_GATE_PROTECTED else f"{g.missed_opportunity_estimate:.2f}"
        print(f"{g.gate:16} "
              f"{g.accepted_good_trades:>9} "
              f"{g.accepted_bad_trades:>8} "
              f"{g.rejected_bad_signals:>8} "
              f"{g.rejected_good_signals:>8} "
              f"{g.false_rejection_rate:>10.3f} "
              f"{g.protection_value:>8.2f} "
              f"{miss_label:>8} "
              f"{g.net_gate_value:>8.2f}")
    print("\nReminder: 'safety' in the miss column marks the risk gate "
          "(rejected_good_signals == safety_correct_rejection, never a miss).")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
