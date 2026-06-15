#!/usr/bin/env python3
"""v3.25 — Conditional outcome scheduling.

For each ShadowFill present in ``learning-loop/shadow_ledger/``
(today's file by default), calls
:func:`shared.outcome_tracker.schedule_outcomes` and appends each
ScheduledOutcome to ``learning-loop/shadow_outcomes/<date>.jsonl``.

If NO fills exist, the script writes nothing and exits cleanly.

HARD SAFETY
-----------
- NEVER imports ``alpaca_orders`` (verified by unit test).
- NEVER makes a network call.
- NEVER fabricates outcomes. ``schedule_outcomes`` is a pure function
  over the in-memory ShadowFill record.
- Outcomes are stamped ``is_paper_trade=False`` by construction (the
  source ShadowFill carries that field).

Usage
-----
::

    python3 scripts/run_conditional_outcome_scheduling.py
    python3 scripts/run_conditional_outcome_scheduling.py --date 2026-06-15
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "shared") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "shared"))


VERSION = "v3.25.0"
SHADOW_LEDGER_DIR = REPO_ROOT / "learning-loop" / "shadow_ledger"
SHADOW_OUTCOMES_DIR = REPO_ROOT / "learning-loop" / "shadow_outcomes"


STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT_BY_THIS_SCRIPT",
    "SHADOW_OUTCOME_IS_OBSERVATION_NOT_TRADE",
    "LLM_ADVISORY_ONLY",
)


def _today_iso_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_fills(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except OSError:
        return []
    return out


class _FillShim:
    """Lightweight stand-in matching the ShadowFill attribute surface
    required by :func:`schedule_outcomes`."""

    def __init__(self, d: dict):
        self.fill_status   = d.get("fill_status")
        self.timestamp_iso = d.get("timestamp_iso")
        self.fill_price    = d.get("fill_price", 0.0)
        self.qty           = d.get("qty", 0.0)
        self.side          = d.get("side", "long")
        self.symbol        = d.get("symbol", "?")
        self.strategy      = d.get("strategy", "unknown")
        self.asset_class   = d.get("asset_class", "us_equity")
        self.signal_id     = d.get("signal_id", "")


def schedule_for_fills(fills: list[dict]) -> list[dict]:
    if not fills:
        return []
    try:
        from outcome_tracker import schedule_outcomes
    except ImportError:
        from shared.outcome_tracker import schedule_outcomes

    out: list[dict] = []
    for f in fills:
        try:
            shim = _FillShim(f)
            scheduled = schedule_outcomes(shim)
            for s in scheduled:
                # Convert dataclass to a dict; stamp the contract bits.
                if is_dataclass(s):
                    record = asdict(s)
                else:
                    record = dict(getattr(s, "__dict__", {}))
                record["record_type"] = "SHADOW_OUTCOME_PENDING"
                record["is_paper_trade"] = False
                record["standing_markers"] = list(STANDING_MARKERS)
                out.append(record)
        except Exception:
            # Fail-soft; never raise from outcome scheduling.
            continue
    return out


def _append_jsonl(path: Path, records: list[dict]) -> None:
    if not records:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as fh:
            for r in records:
                fh.write(json.dumps(r, sort_keys=True, default=str) + "\n")
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="v3.25 conditional shadow outcome scheduling.")
    p.add_argument("--date", type=str, default=_today_iso_date(),
                   help="YYYY-MM-DD date to process. Default = today UTC.")
    p.add_argument("--no-write", action="store_true",
                   help="Compute outcomes but do not persist.")
    args = p.parse_args(argv)

    fill_path = SHADOW_LEDGER_DIR / f"{args.date}.jsonl"
    fills = _load_fills(fill_path)
    n_fills = len(fills)

    scheduled = schedule_for_fills(fills) if n_fills else []

    out_path = SHADOW_OUTCOMES_DIR / f"{args.date}.jsonl"
    if not args.no_write:
        _append_jsonl(out_path, scheduled)

    print(f"v3.25 conditional outcome scheduling — date={args.date}")
    print(f"  fills_loaded={n_fills}")
    print(f"  outcomes_scheduled={len(scheduled)}")
    if n_fills == 0:
        print("  reason=no_shadow_fills_in_ledger_today")
    print(f"standing_markers={'|'.join(STANDING_MARKERS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
