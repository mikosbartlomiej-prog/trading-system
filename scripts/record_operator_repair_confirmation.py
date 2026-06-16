#!/usr/bin/env python3
"""v3.29 ETAP 1 (2026-06-16) — CLI to record operator-confirmed broker repairs.

CONTRACT (do not loosen)
------------------------
This script is **operator-facing**. It writes a JSON marker that other
modules (broker_repair_required, allocator_incident_gate) consult to
decide whether a quarantine can be cleared.

It NEVER:

* calls the broker,
* imports ``alpaca_orders``,
* makes any network call,
* clears safe_mode,
* flips ``LIVE_TRADING`` / ``ALLOW_BROKER_PAPER`` / ``EDGE_GATE_ENABLED``,
* places, cancels, or modifies orders,
* mutates risk thresholds.

It ONLY:

* writes a marker file (after ``--operator-confirmed`` is supplied)
  under ``learning-loop/operator_markers/<symbol>_<date>.json``,
* prints a summary,
* appends an audit JSONL row.

USAGE
-----
::

  python3 scripts/record_operator_repair_confirmation.py \\
      --symbol AVAXUSD \\
      --dashboard-checked \\
      --open-orders-checked \\
      --stale-oco-cancelled true \\
      --position-closed true \\
      --equity-checked \\
      --operator-note "manually closed stuck AVAX dust + cancelled orphan OCO" \\
      --operator-confirmed

Without ``--operator-confirmed`` the script runs in default dry-run
mode and writes nothing — it only prints the would-be payload.

STANDING MARKERS
----------------
- ``EDGE_GATE_ENABLED=false``
- ``ALLOW_BROKER_PAPER=false``
- ``LIVE_TRADING_UNSUPPORTED``
- ``NO_ORDER_PLACEMENT``
- ``NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT``
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Standing invariants (asserted by tests) ───────────────────────────────────
LIVE_TRADING_UNSUPPORTED = True
NO_ORDER_PLACEMENT = True
NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT = True
EDGE_GATE_ENABLED = False
ALLOW_BROKER_PAPER = False


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))

import operator_repair_state as ors  # noqa: E402


_VALID_TRISTATE = {"true", "false", "unknown"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tristate(s: Optional[str]) -> str:
    if s is None:
        return "unknown"
    val = str(s).strip().lower()
    return val if val in _VALID_TRISTATE else "unknown"


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="record_operator_repair_confirmation.py",
        description=(
            "Record a manual broker-repair confirmation marker. "
            "Default is DRY-RUN — must pass --operator-confirmed to write."
        ),
    )
    p.add_argument("--symbol", required=True, help="Symbol that was repaired (e.g. AVAXUSD)")
    p.add_argument("--incident-type", default="P13_BRACKET_INTERLOCK",
                   help="Incident type that triggered the quarantine.")
    p.add_argument("--dashboard-checked", action="store_true",
                   help="Operator confirms they looked at the Alpaca dashboard.")
    p.add_argument("--open-orders-checked", action="store_true",
                   help="Operator confirms they checked open orders for this symbol.")
    p.add_argument("--stale-oco-cancelled", default="unknown",
                   choices=sorted(_VALID_TRISTATE),
                   help="Did operator manually cancel orphaned OCO legs? (true/false/unknown)")
    p.add_argument("--position-closed", default="unknown",
                   choices=sorted(_VALID_TRISTATE),
                   help="Did operator manually close the position? (true/false/unknown)")
    p.add_argument("--final-position-state", default="",
                   help="Free-form note: what is the final position state? (qty=0, etc.)")
    p.add_argument("--final-open-orders-state", default="",
                   help="Free-form note: what is the final open-orders state? (none, etc.)")
    p.add_argument("--equity-checked", action="store_true",
                   help="Operator confirms they checked the account equity.")
    p.add_argument("--operator-note", default="",
                   help="Free-form operator note (e.g. reason, ticket id, etc.)")
    p.add_argument("--operator-confirmed", action="store_true",
                   help="REQUIRED to actually write the marker. Without it, dry-run.")
    p.add_argument("--dry-run", default="auto",
                   help=("Force dry-run mode regardless of --operator-confirmed. "
                         "'true' = always dry; 'false' = let --operator-confirmed decide; "
                         "default 'auto' (same as 'false')."))
    return p.parse_args(argv)


def _str_to_bool(s: str) -> bool:
    return str(s).strip().lower() in {"1", "true", "yes", "on"}


def _build_payload(args: argparse.Namespace) -> ors.OperatorRepairConfirmation:
    return ors.OperatorRepairConfirmation(
        symbol=str(args.symbol),
        incident_type=str(args.incident_type),
        dashboard_checked=bool(args.dashboard_checked),
        open_orders_checked=bool(args.open_orders_checked),
        stale_oco_cancelled_by_operator=_tristate(args.stale_oco_cancelled),
        position_closed_by_operator=_tristate(args.position_closed),
        final_position_state=str(args.final_position_state),
        final_open_orders_state=str(args.final_open_orders_state),
        equity_checked=bool(args.equity_checked),
        operator_note=str(args.operator_note),
        timestamp_iso=_now_iso(),
        # source + does_not_execute_orders forced by operator_repair_state._normalize
    )


def _print_payload(payload: ors.OperatorRepairConfirmation, *, written_to: Optional[Path] = None) -> None:
    body = payload.to_dict()
    print("=== Operator repair confirmation ===")
    print(json.dumps(body, indent=2, sort_keys=True))
    print("--- Standing markers ---")
    for m in ors.standing_markers():
        print(f"  {m}")
    if written_to is not None:
        print(f"--- Written to ---\n  {written_to}")
    else:
        print("--- Dry run --- (no marker written; pass --operator-confirmed to write)")


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)

    # Dry-run resolution: 'true' wins; otherwise --operator-confirmed gates it.
    dry_arg = str(args.dry_run).strip().lower()
    if dry_arg in {"true", "1", "yes"}:
        dry_run = True
    else:
        dry_run = not bool(args.operator_confirmed)

    payload = _build_payload(args)

    if dry_run:
        _print_payload(payload, written_to=None)
        return 0

    written = ors.write_marker(payload)
    _print_payload(payload, written_to=written)
    print("Note: this script does NOT clear broker_repair_required state.")
    print("      Run scripts/verify_manual_broker_repair.py (if applicable)")
    print("      or invoke shared.broker_repair_required.clear_repair() with")
    print("      this marker path to clear quarantine.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
