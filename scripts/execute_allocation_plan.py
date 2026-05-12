#!/usr/bin/env python3
"""
scripts/execute_allocation_plan.py — morning executor.

Runs ~5 min after US market open (cron 35 13 * * 1-5 UTC).
Reads the most recent allocation plan from learning-loop/allocations/<date>.json
and executes the orders if config.auto_execute_rebalance == true.

If auto_execute is OFF the script prints what WOULD be placed and exits 0
(no-op, no email) so the workflow doesn't error on a deliberate hold.

Pre-flight gates (all fail-soft, log + skip):
  - plan file exists for today (or yesterday if today missing — weekend rollover)
  - market is open (defers to shared.market_hours)
  - auto_execute_rebalance flag is true
  - defensive_mode not active (else only EXIT/REDUCE)

Output:
  - stdout trace (mirrors AccountAwareAllocator.trace)
  - learning-loop/allocations/<date>.execution.json (per-order results)
  - [allocator EXEC] email via shared.notify.notify_allocation_execution

Exit code:
  0 — normal completion (regardless of whether any orders placed)
  2 — config error / missing plan file (operator should investigate)

Usage:
  # Normal (cron):
  python -m scripts.execute_allocation_plan

  # Dry-run (force=True equivalent, no Alpaca calls — used by tests):
  python -m scripts.execute_allocation_plan --dry-run

  # Specific date (replay yesterday's plan):
  python -m scripts.execute_allocation_plan --date 2026-05-12
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "shared"))

_ALLOCATIONS_DIR = os.path.join(_REPO_ROOT, "learning-loop", "allocations")


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _yesterday_iso() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def _find_plan(date_hint: str | None) -> tuple[str | None, str | None]:
    """Returns (path, date_iso) or (None, None) if no usable plan."""
    candidates = []
    if date_hint:
        candidates.append(date_hint)
    candidates.extend([_today_iso(), _yesterday_iso()])
    seen = set()
    for d in candidates:
        if d in seen:
            continue
        seen.add(d)
        p = os.path.join(_ALLOCATIONS_DIR, f"{d}.json")
        if os.path.exists(p):
            return p, d
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser(description="Morning allocator executor")
    parser.add_argument("--date", help="Plan date YYYY-MM-DD (default today, fallback yesterday)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip actual Alpaca calls (force=False, plan-only)")
    parser.add_argument("--force", action="store_true",
                        help="Override config.auto_execute_rebalance for this run")
    args = parser.parse_args()

    plan_path, plan_date = _find_plan(args.date)
    if not plan_path:
        print(f"[executor] ERROR: no allocation plan found in {_ALLOCATIONS_DIR}")
        print(f"[executor]        looked for: {args.date or _today_iso()}.json, "
              f"{_yesterday_iso()}.json")
        return 2

    print(f"[executor] loading plan: {plan_path}")
    with open(plan_path) as f:
        plan = json.load(f)

    # Re-instantiate allocator to get fresh config + market hours + execute logic
    from allocator import AccountAwareAllocator
    alloc = AccountAwareAllocator()
    auto_x = bool(alloc.cfg.get("auto_execute_rebalance", False))

    print(f"[executor] plan_date={plan_date}  generated_at={plan.get('generated_at')}")
    print(f"[executor] auto_execute_rebalance={auto_x}  --force={args.force}  --dry-run={args.dry_run}")

    if args.dry_run:
        print("[executor] DRY-RUN: would execute below orders")
        for o in plan.get("rebalance_orders", []):
            if o.get("action") != "HOLD":
                print(f"  [DRYRUN] {o['action']:<6} {o['symbol']:<10} delta={o.get('delta', 0):+.2f}")
        return 0

    if not (auto_x or args.force):
        print("[executor] auto_execute_rebalance=false and --force not set → no orders placed")
        # Operator-friendly stdout dump (so cron logs show what would have run)
        for o in plan.get("rebalance_orders", []):
            if o.get("action") != "HOLD":
                print(f"  [PLAN-ONLY] {o['action']:<6} {o['symbol']:<10} delta={o.get('delta', 0):+.2f}")
        return 0

    # Execute
    results = alloc.execute_orders(plan.get("rebalance_orders") or [], force=args.force)

    # Persist results next to plan
    exec_path = os.path.join(_ALLOCATIONS_DIR, f"{plan_date}.execution.json")
    try:
        with open(exec_path, "w") as f:
            json.dump({
                "plan_date":  plan_date,
                "executed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "n_placed":   sum(1 for r in results if r.get("status") == "placed"),
                "n_skipped":  sum(1 for r in results if r.get("status") == "skipped"),
                "n_failed":   sum(1 for r in results if r.get("status") == "failed"),
                "results":    results,
            }, f, indent=2, ensure_ascii=False)
        print(f"[executor] execution log saved: {os.path.basename(exec_path)}")
    except OSError as e:
        print(f"[executor] execution log write error: {e}")

    # Append execution trace to <date>.log
    log_path = os.path.join(_ALLOCATIONS_DIR, f"{plan_date}.log")
    try:
        with open(log_path, "a") as f:
            f.write("\n" + "\n".join(alloc.trace.lines) + "\n")
    except OSError:
        pass  # log append best-effort

    # Email summary
    try:
        from notify import notify_allocation_execution
        notify_allocation_execution(plan_date, results)
    except Exception as e:
        print(f"[executor] email skipped ({type(e).__name__}: {e})")

    print(f"[executor] done. placed={sum(1 for r in results if r.get('status') == 'placed')} "
          f"skipped={sum(1 for r in results if r.get('status') == 'skipped')} "
          f"failed={sum(1 for r in results if r.get('status') == 'failed')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
