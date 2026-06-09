#!/usr/bin/env python3
"""v3.27.0 (2026-06-09) — shadow outcome resolver entry-point.

Reads PENDING shadow records from
``learning-loop/shadow_evidence/records_YYYY-MM-DD.jsonl`` and writes
hypothetical outcome records to
``learning-loop/shadow_evidence/outcomes_YYYY-MM-DD.jsonl`` (sidecar,
append-only).

DOES NOT submit orders. DOES NOT import ``shared/alpaca_orders.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "false").strip().lower()
    return v in ("true", "1", "yes", "on")


def _refuse_if_broker_enabled() -> str | None:
    for name in (
        "ALLOW_BROKER_PAPER", "EDGE_GATE_ENABLED",
        "BROKER_EXECUTION_ENABLED",
        "LIVE_TRADING", "LIVE_ENABLED", "GO_LIVE",
        "LIVE_TRADING_ENABLED",
    ):
        if _env_truthy(name):
            return f"REFUSED_{name}_IS_TRUTHY"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve PENDING v3.27 shadow records into "
                    "hypothetical outcome records. Read-only.",
    )
    parser.add_argument("--day", type=str, default=None,
                          help="UTC day in YYYY-MM-DD; defaults to today.")
    parser.add_argument("--max-records", type=int, default=50)
    parser.add_argument("--horizon-seconds", type=int, default=3600,
                          help="Minimum age of a record before it is "
                               "eligible for resolution.")
    args = parser.parse_args(argv)

    refuse = _refuse_if_broker_enabled()
    if refuse is not None:
        print(json.dumps({"status": refuse, "version": "v3.27.0"}))
        return 1

    if args.day:
        day = args.day
    else:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    import shadow_outcome_resolver as resolver  # type: ignore
    import market_data_provider as mdp  # type: ignore

    def _fetch(symbol: str, asset_class: str | None):
        return mdp.fetch_snapshot(symbol, asset_class)

    summary = resolver.resolve_day(
        day=day,
        repo_root=REPO_ROOT,
        fetch_snapshot_fn=_fetch,
        horizon_seconds=int(args.horizon_seconds),
        max_records=int(args.max_records),
    )
    summary["status"] = "RESOLVED"
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
