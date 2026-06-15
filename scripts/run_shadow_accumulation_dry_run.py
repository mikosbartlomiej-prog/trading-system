#!/usr/bin/env python3
"""v3.25 — Conditional shadow accumulation dry-run.

Walks post-v3.24 opportunity_ledger rows, runs the eligibility gate
on each, and (in dry-run mode) REPORTS what would be simulated. In
``--dry-run False`` mode and ONLY if at least one row is ELIGIBLE,
delegates to :func:`shared.shadow_simulator.maybe_simulate_from_row`
and appends the returned ShadowFill (if any) to
``learning-loop/shadow_ledger/<YYYY-MM-DD>.jsonl``.

CONTRACT
--------
- Default ``--dry-run=True`` writes NOTHING to the shadow ledger.
- When ``eligible_count == 0``, the script does not switch behaviour
  even if ``--dry-run False`` is requested; it MUST exit having
  written zero fills. The audit row records the reason verbatim.
- Audit rows are written for EVERY decision (ELIGIBLE or not) to
  ``learning-loop/shadow_evidence/shadow_accumulation_audit.jsonl``.
- Standing markers footer is preserved on the audit row.

HARD SAFETY
-----------
- NEVER imports ``alpaca_orders`` (verified by unit test).
- NEVER makes a network call.
- NEVER calls a broker entry point. The ``shared.shadow_simulator``
  module it delegates to is itself NO-BROKER (re-asserts the flags).
- NEVER fabricates a fill. If ``maybe_simulate_from_row`` returns
  ``None`` (which it does whenever the gate fails or whenever any
  broker / live flag is truthy), this script writes nothing.

Usage
-----
::

    # Default — dry run only, no writes.
    python3 scripts/run_shadow_accumulation_dry_run.py

    # Even with --dry-run False, will only write if ELIGIBLE > 0.
    python3 scripts/run_shadow_accumulation_dry_run.py --dry-run False
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "shared") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "shared"))


VERSION = "v3.25.0"
DEFAULT_CUTOFF_ISO = "2026-06-15T11:35:05+00:00"
DEFAULT_LEDGER_DIR = REPO_ROOT / "learning-loop" / "opportunity_ledger"
SHADOW_LEDGER_DIR = REPO_ROOT / "learning-loop" / "shadow_ledger"
SHADOW_EVIDENCE_DIR = REPO_ROOT / "learning-loop" / "shadow_evidence"
AUDIT_FILE = SHADOW_EVIDENCE_DIR / "shadow_accumulation_audit.jsonl"


STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT_BY_THIS_SCRIPT",
    "PURE_LOCAL_FILE_OPERATIONS",
    "NEAR_MISS_IS_NOT_TRADE_EVIDENCE",
    "SHADOW_IS_NOT_BROKER_PAPER",
    "LLM_ADVISORY_ONLY",
)


def _row_timestamp(r: dict) -> str:
    return (
        r.get("timestamp")
        or r.get("emit_timestamp")
        or r.get("written_iso")
        or ""
    )


def _str_to_bool(s: str) -> bool:
    return str(s).strip().lower() in ("1", "true", "yes", "y", "on")


def load_post_cutoff_rows(
    ledger_dir: Path,
    cutoff_iso: str,
    max_files: int = 7,
) -> list[dict]:
    files = sorted(ledger_dir.glob("*.jsonl"))[-max_files:]
    out: list[dict] = []
    for f in files:
        try:
            with open(f) as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    if _row_timestamp(r) >= cutoff_iso:
                        out.append(r)
        except OSError:
            continue
    return out


def _append_audit_row(row: dict[str, Any]) -> None:
    try:
        SHADOW_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_FILE, "a") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        pass


def _append_shadow_fill(fill: Any, as_of_iso: str) -> tuple[bool, str]:
    """Append a ShadowFill to learning-loop/shadow_ledger/<date>.jsonl."""
    try:
        SHADOW_LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        date_str = as_of_iso[:10]
        path = SHADOW_LEDGER_DIR / f"{date_str}.jsonl"
        # Use the fill's to_dict() if available; else __dict__.
        if hasattr(fill, "to_dict"):
            payload = fill.to_dict()
        else:
            payload = {k: v for k, v in vars(fill).items()
                       if not k.startswith("_")}
        with open(path, "a") as fh:
            fh.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
        return True, str(path)
    except Exception as e:
        return False, f"write_failed: {e}"


def process_rows(
    rows: list[dict],
    *,
    dry_run: bool,
    as_of_iso: str,
) -> dict[str, Any]:
    """Evaluate eligibility, optionally produce ShadowFills."""
    # Lazy imports — must work even if siblings are shimmed.
    try:
        from shadow_eligibility import evaluate_shadow_eligibility
    except ImportError:
        from shared.shadow_eligibility import evaluate_shadow_eligibility
    try:
        from shadow_simulator import maybe_simulate_from_row
    except ImportError:
        from shared.shadow_simulator import maybe_simulate_from_row

    decisions: dict[str, int] = {}
    eligible_signal_ids: list[str] = []
    fills_written: list[str] = []
    fills_skipped_dry_run: list[str] = []
    fills_returned_none: list[str] = []

    for r in rows:
        try:
            verdict = evaluate_shadow_eligibility(r)
            tok = verdict.decision.value
            reason = verdict.reason
        except Exception as e:
            tok = "NOT_ELIGIBLE_UNKNOWN"
            reason = f"evaluate raised: {e}"

        decisions[tok] = decisions.get(tok, 0) + 1
        sig_id = r.get("signal_id") or (
            r.get("raw_signal", {}) or {}).get("signal_id") or "?"

        audit = {
            "version":          VERSION,
            "as_of_iso":        as_of_iso,
            "signal_id":        sig_id,
            "decision":         tok,
            "reason":           reason,
            "dry_run":          dry_run,
            "standing_markers": list(STANDING_MARKERS),
            "fill_written":     False,
            "fill_path":        None,
        }

        if tok == "ELIGIBLE":
            eligible_signal_ids.append(sig_id)
            if dry_run:
                fills_skipped_dry_run.append(sig_id)
                audit["fill_written"] = False
                audit["note"] = "dry-run; would-have-simulated"
            else:
                # Delegate to the simulator (which itself re-asserts
                # broker/live flag safety + eligibility).
                fill = None
                try:
                    fill = maybe_simulate_from_row(r)
                except Exception as e:
                    audit["note"] = f"simulator raised: {e}"
                if fill is None:
                    fills_returned_none.append(sig_id)
                    audit["note"] = audit.get(
                        "note", "simulator returned None")
                else:
                    ok, path = _append_shadow_fill(fill, as_of_iso)
                    audit["fill_written"] = ok
                    audit["fill_path"] = path
                    if ok:
                        fills_written.append(sig_id)

        _append_audit_row(audit)

    return {
        "rows_evaluated":         len(rows),
        "eligible_count":         decisions.get("ELIGIBLE", 0),
        "decisions":              decisions,
        "eligible_signal_ids":    eligible_signal_ids,
        "fills_written":          fills_written,
        "fills_skipped_dry_run":  fills_skipped_dry_run,
        "fills_returned_none":    fills_returned_none,
        "dry_run":                dry_run,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="v3.25 conditional shadow accumulation dry-run.",
    )
    p.add_argument("--ledger-dir", type=Path, default=DEFAULT_LEDGER_DIR)
    p.add_argument("--cutoff-iso", type=str, default=DEFAULT_CUTOFF_ISO)
    p.add_argument("--as-of", type=str, default=None,
                   help="ISO timestamp (defaults to now UTC).")
    p.add_argument("--dry-run", type=str, default="True",
                   help="True (default) = report only. False = "
                        "simulate IF AND ONLY IF eligible > 0.")
    p.add_argument("--max-files", type=int, default=7)
    args = p.parse_args(argv)

    dry_run = _str_to_bool(args.dry_run)
    as_of_iso = (
        args.as_of or datetime.now(timezone.utc).isoformat()
    )

    rows = load_post_cutoff_rows(
        args.ledger_dir, args.cutoff_iso, args.max_files)
    summary = process_rows(rows, dry_run=dry_run, as_of_iso=as_of_iso)

    if dry_run:
        mode = "DRY-RUN (default)"
    else:
        mode = "EXECUTE" if summary["eligible_count"] > 0 \
            else "NO-OP (0 eligible)"

    print(f"v3.25 shadow accumulation — mode={mode}")
    print(f"  rows_evaluated={summary['rows_evaluated']}")
    print(f"  eligible_count={summary['eligible_count']}")
    print(f"  decisions={summary['decisions']}")
    if dry_run:
        print(f"  would_simulate_signal_ids="
              f"{summary['fills_skipped_dry_run']}")
    else:
        print(f"  fills_written={summary['fills_written']}")
        print(f"  fills_returned_none={summary['fills_returned_none']}")
    print(f"standing_markers={'|'.join(STANDING_MARKERS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
