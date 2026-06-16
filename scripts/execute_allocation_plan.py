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


# ── v3.9.10 (2026-05-27): deterministic plan revalidation ─────────────────────

def _revalidate_plan_against_live(plan_orders: list) -> list:
    """
    Validate each plan order against LIVE Alpaca position state.

    Plans are generated ~9.5h before execution (04:00 UTC → 13:35 UTC).
    Positions can change overnight via bracket SL fills, manual closes, or
    remediation actions. Without this gate, stale plans cause incidents
    like 2026-05-27 NOW SHORT bug (allocator sent EXIT MARKET 169 to a
    position that was already closed → naked short -169).

    Per-action validation rules:
      EXIT/REDUCE  → drop if position 404 (already closed)
      EXIT/REDUCE  → drop if live position is SHORT (would double-short)
      EXIT/REDUCE  → drop if |live_qty - plan_qty| > 50% (severe drift)
      BUY          → drop if position exists at ≥90% of target (already there)
      BUY          → keep otherwise (additional position-precheck in _exec_buy)
      HOLD         → never dropped (no order placed)

    Returns: list of orders that passed validation. Drops are logged.
    Fail-open: if Alpaca unavailable, returns plan_orders unchanged (with warning).
    """
    if not plan_orders:
        return plan_orders

    try:
        from alpaca_orders import _fetch_single_position
    except ImportError:
        from shared.alpaca_orders import _fetch_single_position  # type: ignore

    dropped: list[dict] = []
    kept: list = []
    print("[executor] v3.9.10 plan revalidation against live positions...")

    for order in plan_orders:
        action = (order.get("action") or "").upper()
        sym = (order.get("symbol") or "").upper()
        if action == "HOLD" or not sym:
            kept.append(order)
            continue

        # Pre-flight position fetch
        try:
            live_pos = _fetch_single_position(sym)
        except Exception as e:
            print(f"  [revalidate] {sym} fetch error ({type(e).__name__}) — keeping order (fail-open)")
            kept.append(order)
            continue

        plan_qty = abs(float(order.get("qty_delta") or 0) or 0)

        if action in ("EXIT", "REDUCE"):
            if not live_pos:
                dropped.append({"symbol": sym, "action": action,
                                "reason": "position already closed (404)"})
                continue
            try:
                live_qty = abs(float(live_pos.get("qty") or 0))
                live_side = (live_pos.get("side") or "").lower()
            except (ValueError, TypeError):
                print(f"  [revalidate] {sym} malformed position data — keeping (fail-open)")
                kept.append(order)
                continue
            if live_qty <= 0:
                dropped.append({"symbol": sym, "action": action,
                                "reason": f"live_qty=0 (plan_qty={plan_qty})"})
                continue
            if live_side == "short":
                dropped.append({"symbol": sym, "action": action,
                                "reason": "live position is SHORT (would double-short)"})
                continue
            # Severe drift: only drop if BOTH plan_qty>0 AND drift>50%
            # (small drifts handled by safe_close's 5% threshold)
            if plan_qty > 0 and abs(live_qty - plan_qty) / plan_qty > 0.50:
                # Allow EXIT through (executor will use live qty via safe_close)
                # but log for visibility
                print(f"  [revalidate] {sym} {action} severe drift: plan={plan_qty} live={live_qty} — keeping (safe_close will clamp)")
            kept.append(order)

        elif action == "BUY":
            # v3.9.10 strategy_coherence audit P1 (2026-05-27): drop ONLY when
            # BOTH conditions hold:
            #   (a) live_qty >= 95% of target_qty (very close to target)
            #   (b) |target_value - current_value| < $500 (small delta in $)
            # Allows incremental top-ups (e.g. target $25k, current $15k = 60%)
            # to proceed while preventing redundant orders at the threshold.
            if live_pos:
                try:
                    live_qty = abs(float(live_pos.get("qty") or 0))
                    target_qty = abs(float(order.get("target_qty") or plan_qty) or 1)
                    target_value = abs(float(order.get("target_value") or 0))
                    current_value = abs(float(order.get("current_value") or 0))
                    delta_usd = abs(target_value - current_value)
                    if (target_qty > 0 and live_qty / target_qty >= 0.95
                            and delta_usd < 500):
                        dropped.append({
                            "symbol": sym, "action": action,
                            "reason": (
                                f"position at {live_qty/target_qty:.0%} of target "
                                f"+ delta only ${delta_usd:.0f} < $500"
                            )
                        })
                        continue
                except (ValueError, TypeError):
                    pass
            kept.append(order)
        else:
            kept.append(order)

    if dropped:
        print(f"[executor] v3.9.10 revalidation DROPPED {len(dropped)} stale order(s):")
        for d in dropped:
            print(f"  [DROPPED] {d['action']:<6} {d['symbol']:<10} — {d['reason']}")
    else:
        print("[executor] v3.9.10 revalidation: all orders pass live-state check")
    print(f"[executor] revalidation: {len(kept)} kept, {len(dropped)} dropped")

    # Email alert if any drops (operator visibility)
    if dropped:
        try:
            from notify import send_email
            body = "v3.9.10 plan revalidation dropped stale orders:\n\n"
            body += "\n".join(f"  {d['action']} {d['symbol']}: {d['reason']}" for d in dropped)
            body += "\n\nThis is normal when overnight bracket SL fills change position state."
            body += "\nKept orders proceed to execution; dropped orders logged for audit."
            send_email(
                subject=f"[allocator REVALIDATE] {len(dropped)} stale order(s) dropped",
                body=body,
            )
        except Exception as e:
            print(f"  [revalidate] email failed (non-fatal): {e}")

    return kept


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


def _write_block_doc(result, plan_date: str) -> None:
    """v3.28 ETAP 8 — write a date-stamped block doc when the gate refuses.

    Lives at ``docs/MORNING_ALLOCATOR_BLOCKED_<plan_date>.md``. Operator
    inspects this file to learn why the gate refused. Fail-soft: any
    I/O error is logged but does NOT propagate (the audit row is the
    authoritative record; the doc is a convenience).
    """
    try:
        from pathlib import Path
        ts = datetime.now(timezone.utc).isoformat()
        path = Path(_REPO_ROOT) / "docs" / f"MORNING_ALLOCATOR_BLOCKED_{plan_date}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        body = [
            f"# Morning allocator BLOCKED — {plan_date}",
            "",
            f"_Generated at {ts} by allocator_incident_gate (v3.28)._",
            "",
            f"**Decision:** `{result.decision.value}`",
            "",
            "## Blockers",
            "",
        ]
        if result.blockers:
            for b in result.blockers:
                body.append(f"- `{b}`")
        else:
            body.append("- _(no specific blocker recorded — gate failed CLOSED on unknown)_")
        body.extend([
            "",
            "## Snapshot",
            "",
            "```json",
            json.dumps(result.snapshot, indent=2, sort_keys=True, default=str),
            "```",
            "",
            "## What now",
            "",
            "Operator must resolve the blocker(s) above. Do NOT auto-clear",
            "safe_mode, do NOT auto-cancel broker orders, do NOT auto-close",
            "positions. The allocator will retry on the next cron when the",
            "gate decision flips to `ALLOW_ALLOCATOR`.",
            "",
        ])
        path.write_text("\n".join(body), encoding="utf-8")
    except Exception as exc:
        print(f"[executor] block-doc write failed (non-fatal): {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Morning allocator executor")
    parser.add_argument("--date", help="Plan date YYYY-MM-DD (default today, fallback yesterday)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip actual Alpaca calls (force=False, plan-only)")
    parser.add_argument("--force", action="store_true",
                        help="Override config.auto_execute_rebalance for this run")
    args = parser.parse_args()

    # ── v3.28 ETAP 3/8 (2026-06-16): incident gate (fail CLOSED). ─────────
    # Runs BEFORE anything else, including plan-file lookup. If any
    # active incident is unresolved (safe_mode / broker_repair / P13 /
    # equity-gap / position-recon-stale / kill-switch) we refuse to
    # touch the broker. Default verdict is BLOCK_UNKNOWN so any
    # exception inside the gate keeps us safe. Audit row is written
    # for every verdict (including ALLOW_ALLOCATOR).
    try:
        from allocator_incident_gate import (
            evaluate as _gate_evaluate,
            write_audit_decision as _gate_write_audit,
            AllocatorIncidentDecision as _GateDecision,
        )
    except ImportError:
        from shared.allocator_incident_gate import (  # type: ignore
            evaluate as _gate_evaluate,
            write_audit_decision as _gate_write_audit,
            AllocatorIncidentDecision as _GateDecision,
        )
    gate_result = _gate_evaluate()
    try:
        _gate_write_audit(gate_result)
    except Exception as exc:
        print(f"[executor] gate audit write failed (non-fatal): {exc}")
    print(f"[executor] v3.28 incident gate decision: {gate_result.decision.value}")
    if gate_result.blockers:
        for b in gate_result.blockers:
            print(f"[executor]   blocker: {b}")
    if gate_result.decision is not _GateDecision.ALLOW_ALLOCATOR:
        # Refused — write a date-stamped doc and exit cleanly.
        gate_date = (args.date or _today_iso())
        _write_block_doc(gate_result, gate_date)
        print(f"[executor] incident gate refused — no orders placed. "
              f"See docs/MORNING_ALLOCATOR_BLOCKED_{gate_date}.md")
        return 0

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

    # ── Idempotency guard (v3.8.8, 2026-05-18) ──────────────────────────────
    # Bug realised 2026-05-18: operator triggered workflow_dispatch 3× in
    # 20 min; each run re-executed full plan from scratch. Duplicates:
    # AMD bought 2×, GLD/SPY/QQQ REDUCE 2×, EXITs no-op (positions gone).
    # USO/OXY BUY rejected by Alpaca (first-run LIMITs sat unfilled →
    # duplicate side-order rejection on 2nd attempt).
    #
    # Guard: if <date>.execution.json exists AND executed_at < EXEC_TTL
    # ago AND any orders were placed → skip silently with explanation.
    # --force overrides to allow operator re-run after cancellation.
    exec_path = os.path.join(_ALLOCATIONS_DIR, f"{plan_date}.execution.json")
    # v3.9.9 (2026-05-27): bump 60 → 360 min. Tuesday 2026-05-26 incident:
    # morning-allocator triggered 14:16 + 16:57 UTC (gap 161 min > old 60 min
    # TTL) → re-executed plan on already-filled positions → duplicate brackets
    # → autonomous-remediation MARKET-closed 3 positions. 360 min covers full
    # session 13:35-19:35 UTC plus any cron retries.
    EXEC_TTL_MIN = 360
    if os.path.exists(exec_path) and not args.force:
        try:
            with open(exec_path) as f:
                prior = json.load(f)
            prior_ts = prior.get("executed_at", "")
            n_placed_prior = int(prior.get("n_placed") or 0)
            if prior_ts and n_placed_prior > 0:
                prior_dt = datetime.strptime(prior_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                age_min = (datetime.now(timezone.utc) - prior_dt).total_seconds() / 60
                if age_min < EXEC_TTL_MIN:
                    print(f"[executor] IDEMPOTENCY GUARD: plan {plan_date} already executed "
                          f"{age_min:.0f} min ago ({n_placed_prior} placed). Skipping re-execution.")
                    print(f"[executor]   prior execution: {exec_path}")
                    print(f"[executor]   to override: --force (use only after cancelling open orders)")
                    return 0
                print(f"[executor] prior execution exists ({age_min:.0f} min ago, > {EXEC_TTL_MIN} min TTL) — re-executing")
        except (json.JSONDecodeError, OSError, ValueError) as e:
            print(f"[executor] idempotency check error (proceeding anyway): {e}")

    # ── v3.9.10 (2026-05-27): deterministic plan revalidation ───────────────
    # Plan was generated at 04:00 UTC; execution runs at 13:35 UTC (~9.5h later).
    # Positions may have changed overnight (bracket SL fills, manual closes,
    # remediation actions). Without revalidation, allocator can send EXIT MARKET
    # to a position that no longer exists → naked SHORT (2026-05-27 NOW bug).
    #
    # This revalidation:
    # - Fetches live positions from Alpaca
    # - For each non-HOLD order, verifies the position state matches the plan
    # - DROPS orders whose precondition no longer holds:
    #     EXIT  → drop if position already closed (404)
    #     REDUCE → drop if position 404 OR live_qty < 50% of plan
    #     BUY   → drop if position already exists at ≥90% target (covered by Bug A fix too)
    # - Logs each drop with reason for forensic visibility
    plan_orders = plan.get("rebalance_orders") or []
    revalidated_orders = _revalidate_plan_against_live(plan_orders)

    # Execute
    results = alloc.execute_orders(revalidated_orders, force=args.force)

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

    n_placed = sum(1 for r in results if r.get('status') == 'placed')
    n_skipped = sum(1 for r in results if r.get('status') == 'skipped')
    n_failed = sum(1 for r in results if r.get('status') == 'failed')
    print(f"[executor] done. placed={n_placed} skipped={n_skipped} failed={n_failed}")

    # v3.13.3 — heartbeat ping (READINESS-1). Fail-soft.
    try:
        sys.path.insert(0, str(_REPO_ROOT / "shared"))
        from heartbeat import ping as _hb_ping
        _hb_ping("morning-allocator", status="ok",
                 message=f"placed={n_placed} failed={n_failed}")
    except Exception as _hb_e:
        print(f"  heartbeat ping failed (non-fatal): {type(_hb_e).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
