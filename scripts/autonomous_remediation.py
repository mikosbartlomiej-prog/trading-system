#!/usr/bin/env python3
"""
CLI entry-point for autonomous health remediation.

Pipeline:
  1. Fetch /v2/account + positions + open_orders
  2. Run `scripts/trading_health.py::run_all_checks()`
  3. Hand the result to `shared/remediation.py::remediate()`
  4. Run `shared/emergency_engine.py::scan_emergency_conditions()` and
     `execute_emergency_close()` for any matches

Paper-only. No human approval. Audit JSONL written via
`shared/audit.py::write_audit_event`.

Triggered by `.github/workflows/autonomous-remediation.yml`.

Exit codes:
  0 — completed (some actions may have been taken)
  2 — DEGRADED (health says DEGRADED)
  3 — BLOCKED (health says BLOCKED — operator should investigate)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                    help="Plan remediations but don't call Alpaca")
    p.add_argument("--out-json", help="Write summary JSON to this path")
    args = p.parse_args()

    from autonomy import assert_paper_only, PAPER_BASE_URL, PaperOnlyViolation
    try:
        assert_paper_only(PAPER_BASE_URL)
    except PaperOnlyViolation as e:
        print(f"FATAL paper-only violation: {e}", file=sys.stderr)
        return 3

    # Health
    from trading_health import run_all_checks
    health = run_all_checks()

    # Remediate health-derived issues
    from remediation import remediate
    rem_report = remediate(health, dry_run=args.dry_run, actor="autonomous_remediation")

    # Emergency engine — look for positions that need closing regardless of
    # whether health flagged them (health only sees aggregate flags).
    from emergency_engine import scan_emergency_conditions, execute_emergency_close

    positions_check = next((c for c in health.get("checks", [])
                             if c.get("name") == "positions_fetch"), {}) or {}
    orders_check = next((c for c in health.get("checks", [])
                          if c.get("name") == "orders_fetch"), {}) or {}
    auth_check = next((c for c in health.get("checks", [])
                       if c.get("name") == "alpaca_auth"), {}) or {}

    account = auth_check.get("account")
    positions = positions_check.get("positions") or []
    orders = orders_check.get("orders") or []

    em_targets = scan_emergency_conditions(account, positions, orders, state=None)
    em_results = []
    for tgt in em_targets:
        em_results.append(execute_emergency_close(tgt, dry_run=args.dry_run,
                                                   actor="autonomous_remediation"))

    summary = {
        "health_severity":      health.get("max_severity", "OK"),
        "remediation":          {
            "actions_taken": rem_report.actions_taken,
            "skipped":       rem_report.skipped,
            "blocked":       rem_report.blocked,
            "block_reasons": rem_report.block_reasons,
        },
        "emergency_closes":     em_results,
        "dry_run":              args.dry_run,
    }

    out_text = json.dumps(summary, indent=2, default=str)
    if args.out_json:
        Path(args.out_json).write_text(out_text)
    else:
        print(out_text)

    sev = health.get("max_severity", "OK")
    return {"OK": 0, "WARN": 0, "DEGRADED": 2, "BLOCKED": 3}.get(sev, 0)


if __name__ == "__main__":
    sys.exit(main())
