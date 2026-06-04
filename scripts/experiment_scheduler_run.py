#!/usr/bin/env python3
"""v3.20.0 (2026-06-04) — CLI for shared/experiment_scheduler.py.

Generates the daily observation plan and writes it to disk. Inputs are
best-effort; missing inputs simply produce empty sections — the plan is
NEVER trade-generating.

USAGE
-----
    python3 scripts/experiment_scheduler_run.py
    python3 scripts/experiment_scheduler_run.py \\
        --ranking learning-loop/strategy_ranking_latest.json \\
        --ledger learning-loop/opportunity_ledger.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "shared") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "shared"))


def _load_json_file(path: str | None) -> Any:
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"WARN: cannot read {path}: {e}", file=sys.stderr)
        return None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=("Generate the experiment observation plan. "
                     "Reads ranking + ledger + calibration + bounds "
                     "from JSON (all optional). Writes the plan to "
                     "learning-loop/experiment_plans/ + docs/."))
    p.add_argument("--ranking", default=None,
                   help="Path to strategy ranking JSON.")
    p.add_argument("--ledger", default=None,
                   help="Path to opportunity ledger JSON.")
    p.add_argument("--calibration", default=None,
                   help="Path to confidence calibration JSON.")
    p.add_argument("--evidence-bounds", default=None,
                   help="Path to evidence lower bounds JSON.")
    p.add_argument("--no-write", action="store_true",
                   help="Print plan to stdout without writing to disk.")
    p.add_argument("--audit", action="store_true",
                   help="Emit an audit event (PAUSE/RESUME — diagnostic).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        try:
            from experiment_scheduler import (
                generate_plan, write_plan_to_disk, emit_audit_event,
            )
        except ImportError:
            from shared.experiment_scheduler import (  # type: ignore
                generate_plan, write_plan_to_disk, emit_audit_event,
            )
    except ImportError as e:
        print(f"ERROR: cannot import experiment_scheduler: {e}",
              file=sys.stderr)
        return 2

    plan = generate_plan(
        strategy_ranking=_load_json_file(args.ranking),
        opportunity_ledger=_load_json_file(args.ledger),
        confidence_calibration=_load_json_file(args.calibration),
        evidence_lower_bounds=_load_json_file(args.evidence_bounds),
    )

    if args.no_write:
        print(json.dumps(plan, indent=2, sort_keys=True, default=str))
        return 0

    paths = write_plan_to_disk(plan)
    for p in paths:
        print(f"wrote {p}")

    if args.audit:
        emit_audit_event("plan_generated", plan)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
