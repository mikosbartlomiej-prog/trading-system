"""
Autonomous health-remediation engine.

Reads the output of `scripts/trading_health.py::run_all_checks()` and
turns each non-OK check into a deterministic remediation action. Every
action is paper-only, audited, and rate-limited.

Allowed actions (spec §4):
  CANCEL_STALE_ORDERS       (uses Alpaca DELETE /v2/orders/{id})
  RECREATE_EXIT_PLAN        (places fresh SELL LIMIT for unprotected pos)
  PAUSE_STRATEGY            (writes paused_until via state_policy guard)
  BLOCK_NEW_ENTRIES         (returns a global flag the dispatchers honour)
  EMERGENCY_CLOSE           (delegates to shared.emergency_engine)
  PANIC_CLOSE_OPTIONS       (delegates to scripts/panic_close_options.py
                            in autonomous mode)

Public API:
  remediate(health_result) -> RemediationReport
  list_actions(health_result) -> list[RemediationAction]

Cooldown: per (action_type, symbol/strategy) — default 1h — prevents
remediation loops if the underlying issue is permanent.
"""

from __future__ import annotations

import os
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests

try:
    from autonomy import (
        assert_paper_only, make_decision, PaperOnlyViolation, PAPER_BASE_URL,
    )
    from audit import write_audit_event
    from emergency_engine import scan_emergency_conditions, execute_emergency_close
except ImportError:  # pragma: no cover
    from shared.autonomy import (  # type: ignore
        assert_paper_only, make_decision, PaperOnlyViolation, PAPER_BASE_URL,
    )
    from shared.audit import write_audit_event  # type: ignore
    from shared.emergency_engine import (  # type: ignore
        scan_emergency_conditions, execute_emergency_close,
    )


ALPACA_BASE_URL = PAPER_BASE_URL


REMEDIATION_COOLDOWN_S = int(os.environ.get("REMEDIATION_COOLDOWN_S", "3600"))
MAX_PAUSE_PER_DAY      = int(os.environ.get("REMEDIATION_MAX_PAUSE_PER_DAY", "10"))


# ─── Cooldown map (in-process; survives one cron tick only) ──────────────────

_cooldown: dict[str, float] = {}


def _cooldown_key(action: str, subject: str) -> str:
    return f"{action}|{subject}".lower()


def _cooldown_ok(action: str, subject: str) -> bool:
    last = _cooldown.get(_cooldown_key(action, subject), 0.0)
    return time.time() - last >= REMEDIATION_COOLDOWN_S


def _stamp_cooldown(action: str, subject: str) -> None:
    _cooldown[_cooldown_key(action, subject)] = time.time()


# ─── Action types ─────────────────────────────────────────────────────────────

@dataclass
class RemediationAction:
    action: str                     # one of decision types above
    subject: str                    # symbol or strategy name
    reason: str
    severity: str = "WARN"          # WARN/DEGRADED/BLOCKED from health
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RemediationReport:
    actions_taken: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    blocked: bool = False           # global "block new entries" flag
    block_reasons: list[str] = field(default_factory=list)


# ─── Plan ─────────────────────────────────────────────────────────────────────

def list_actions(health_result: dict) -> list[RemediationAction]:
    """
    Translate health check output → list of deterministic remediations.

    Does NOT execute. Pure function, easy to test.
    """
    actions: list[RemediationAction] = []
    checks = health_result.get("checks") or []
    by_name = {c.get("name"): c for c in checks}

    # 1. CANCEL_STALE_ORDERS
    stale = by_name.get("stale_orders") or {}
    for item in (stale.get("stale") or []):
        sym = (item.get("symbol") or "").upper()
        if not sym:
            continue
        actions.append(RemediationAction(
            action="CANCEL_STALE_ORDERS", subject=sym,
            reason=f"order {item.get('id')} age={item.get('age_hours')}h",
            severity="WARN", metadata={"order_id": item.get("id")},
        ))

    # 2. RECREATE_EXIT_PLAN — handled by emergency_engine "no_exit_plan"
    no_exit = by_name.get("positions_have_exit") or {}
    for sym in (no_exit.get("missing") or []):
        actions.append(RemediationAction(
            action="RECREATE_EXIT_PLAN", subject=sym,
            reason="position has no exit order",
            severity="WARN",
        ))

    # 3. DUPLICATE EXITS → CLEANUP
    dups = by_name.get("duplicate_exits") or {}
    for triple in (dups.get("duplicates") or []):
        if not isinstance(triple, (list, tuple)) or len(triple) < 2:
            continue
        sym = (triple[0] or "").upper()
        actions.append(RemediationAction(
            action="CANCEL_STALE_ORDERS", subject=sym,
            reason="duplicate exit orders",
            severity="WARN", metadata={"keep_one": True},
        ))

    # 4. BLOCK_NEW_ENTRIES on any BLOCKED check
    if (health_result.get("max_severity") or "OK") in ("BLOCKED", "DEGRADED"):
        for c in checks:
            if (c.get("severity") or "OK") in ("BLOCKED", "DEGRADED"):
                actions.append(RemediationAction(
                    action="BLOCK_NEW_ENTRIES", subject="*",
                    reason=f"{c.get('name')} = {c.get('severity')}: {c.get('detail')}",
                    severity=c.get("severity") or "DEGRADED",
                ))

    # 5. PANIC_CLOSE_OPTIONS — if options safety reports BLOCKED, escalate
    opts = by_name.get("options_safety") or {}
    if opts.get("severity") == "BLOCKED":
        actions.append(RemediationAction(
            action="PANIC_CLOSE_OPTIONS", subject="*",
            reason=opts.get("detail") or "options safety BLOCKED",
            severity="BLOCKED",
        ))

    return actions


# ─── Execute (paper-only) ─────────────────────────────────────────────────────

def _headers() -> dict:
    return {
        "APCA-API-KEY-ID":     os.environ.get("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.environ.get("ALPACA_SECRET_KEY", ""),
    }


def _cancel_order(order_id: str) -> bool:
    assert_paper_only(ALPACA_BASE_URL)
    try:
        r = requests.delete(f"{ALPACA_BASE_URL}/v2/orders/{order_id}",
                            headers=_headers(), timeout=10)
        return r.status_code in (200, 204)
    except Exception:
        return False


def _do_cancel_stale(action: RemediationAction) -> dict:
    oid = action.metadata.get("order_id")
    if not oid:
        # generic case: cancel everything open for symbol (used by duplicate-exit cleanup)
        try:
            r = requests.get(f"{ALPACA_BASE_URL}/v2/orders",
                             headers=_headers(),
                             params={"status": "open", "symbols": action.subject},
                             timeout=10)
            cancelled = 0
            if r.status_code == 200:
                orders = r.json() or []
                # If duplicate-exit cleanup, keep one of the SELL orders.
                if action.metadata.get("keep_one"):
                    sells = [o for o in orders
                             if (o.get("side") or "").lower() == "sell"]
                    sells = sorted(sells, key=lambda o: o.get("submitted_at") or "")
                    # Cancel all but the first (oldest = "keep one we already had")
                    for o in sells[1:]:
                        if _cancel_order(o.get("id") or ""):
                            cancelled += 1
                else:
                    for o in orders:
                        if _cancel_order(o.get("id") or ""):
                            cancelled += 1
            return {"ok": cancelled > 0, "cancelled": cancelled}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": _cancel_order(oid), "cancelled": 1, "order_id": oid}


def _do_recreate_exit_plan(action: RemediationAction) -> dict:
    """
    Restore exit protection (LIMIT @ TP + STOP @ SL paired as OCO, GTC) for
    a position whose bracket children expired or were canceled.

    v3.9.6 (2026-05-22 post-incident fix). Previous behavior was to call
    `execute_emergency_close` which MARKET-closes the position — but
    docstring intent was always "restore protection". The 2026-05-22
    incident (see docs/INCIDENT-2026-05-22-positions-closed.md) revealed
    this docstring/code divergence: every overnight bracket DAY-TIF
    expiration triggered a market close at next session open. v3.9.6
    behavior:

      1. Fetch current position (qty, avg_entry_price, side)
      2. Compute TP/SL prices from asset-class strategy defaults
         (stocks_etf: TP +18%, SL -6%; crypto tier1: +20% / -7%;
         options: handled separately via options-exit-monitor)
      3. Submit OCO exit pair (LIMIT @ TP + STOP @ SL, GTC TIF)
      4. Position remains OPEN — only protection restored

    Returns dict with ok / placed orders.

    Env safety: REMEDIATION_DISABLE_RECREATE=true skips this action.
    """
    sym = action.subject

    # Env safety net — operator can disable RECREATE_EXIT_PLAN entirely
    # while the proper fix is being verified. Default behavior is enabled.
    if os.environ.get("REMEDIATION_DISABLE_RECREATE", "").lower() == "true":
        return {
            "ok":      False,
            "skipped": True,
            "reason":  "REMEDIATION_DISABLE_RECREATE env flag set "
                       "(positions left naked overnight per operator override)",
        }

    # Fetch position from Alpaca
    try:
        from alpaca_orders import _fetch_single_position, place_oco_exit
    except ImportError:
        from shared.alpaca_orders import _fetch_single_position, place_oco_exit  # type: ignore

    pos = _fetch_single_position(sym)
    if not pos:
        return {"ok": False, "reason": f"position {sym} not found in Alpaca"}

    try:
        qty = int(abs(float(pos.get("qty", 0))))
        entry = float(pos.get("avg_entry_price", 0))
        pos_side = (pos.get("side") or "long").lower()
    except (TypeError, ValueError) as e:
        return {"ok": False, "reason": f"position {sym} unparseable: {e}"}

    if qty < 1 or entry <= 0:
        return {"ok": False, "reason": f"position {sym} qty={qty} entry={entry} invalid"}

    # Load TP/SL pct from strategy defaults per asset class
    is_crypto = "/" in sym
    is_option = len(sym) > 7 and any(ch.isdigit() for ch in sym)

    if is_option:
        # Options are handled by options-exit-monitor; remediation should
        # not touch them. Return skip.
        return {
            "ok":      False,
            "skipped": True,
            "reason":  f"{sym} is an option — options-exit-monitor handles exits",
        }

    # Stock/ETF defaults from aggressive_profile.json
    tp_pct = 0.18   # +18% take_profit_full_pct
    sl_pct = 0.06   # -6% stop_loss_pct
    try:
        from profile import load_profile
    except ImportError:
        try:
            from shared.profile import load_profile  # type: ignore
        except ImportError:
            load_profile = None  # type: ignore

    if load_profile:
        try:
            prof = load_profile() or {}
            exits = prof.get("exits") or {}
            if is_crypto:
                cdef = exits.get("crypto") or {}
                tp_pct = float(cdef.get("tier1_tp_pct") or tp_pct)
                sl_pct = float(cdef.get("tier1_sl_pct") or sl_pct)
            else:
                sdef = exits.get("stocks_etf") or {}
                tp_pct = float(sdef.get("take_profit_full_pct") or tp_pct)
                sl_pct = float(sdef.get("stop_loss_pct") or sl_pct)
        except Exception:
            pass  # fall back to hardcoded defaults

    # Crypto: Alpaca paper doesn't support OCO on crypto — skip with reason
    if is_crypto:
        return {
            "ok":      False,
            "skipped": True,
            "reason":  f"{sym} is crypto — OCO not supported; rely on price polling",
        }

    # Compute TP/SL absolute prices
    if pos_side == "long":
        tp_price = round(entry * (1 + tp_pct), 2)
        sl_price = round(entry * (1 - sl_pct), 2)
        side = "sell"
    else:  # short
        tp_price = round(entry * (1 - tp_pct), 2)
        sl_price = round(entry * (1 + sl_pct), 2)
        side = "buy_to_cover"

    # Submit OCO
    result = place_oco_exit(sym, qty, tp_price, sl_price, side=side,
                             client_order_id_prefix="recreate-exit")

    if result:
        return {
            "ok":         True,
            "symbol":     sym,
            "qty":        qty,
            "entry":      entry,
            "tp_price":   tp_price,
            "sl_price":   sl_price,
            "order_id":   result.get("id", "")[:12],
            "client_order_id": result.get("client_order_id", ""),
        }
    return {
        "ok":     False,
        "reason": f"OCO submission failed for {sym} qty={qty} tp={tp_price} sl={sl_price}",
    }


def _do_block_new_entries(action: RemediationAction) -> dict:
    """No-op execution; the BLOCK flag is exposed via RemediationReport.blocked."""
    return {"ok": True, "blocked": True}


def _do_panic_close_options(action: RemediationAction) -> dict:
    """
    Trigger panic_close_options in autonomous mode (no human CONFIRM).

    We invoke the function via a subprocess so output flows to the
    workflow log; if subprocess fails we surface the error.
    """
    import subprocess
    env = os.environ.copy()
    env["AUTONOMOUS_PANIC_CLOSE_OPTIONS"] = "true"   # autonomous trigger
    env["CONFIRM_PANIC_CLOSE_OPTIONS"]    = "true"   # script's explicit-confirm flag
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    try:
        r = subprocess.run(
            ["python3", os.path.join(repo_root, "scripts", "panic_close_options.py")],
            env=env, capture_output=True, text=True, timeout=300,
        )
        return {
            "ok":      r.returncode == 0,
            "stdout":  r.stdout[-2000:],
            "stderr":  r.stderr[-2000:],
            "rc":      r.returncode,
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


_DISPATCH = {
    "CANCEL_STALE_ORDERS":  _do_cancel_stale,
    "RECREATE_EXIT_PLAN":   _do_recreate_exit_plan,
    "BLOCK_NEW_ENTRIES":    _do_block_new_entries,
    "PANIC_CLOSE_OPTIONS":  _do_panic_close_options,
}


def remediate(health_result: dict, *, dry_run: bool = False,
              actor: str = "remediation") -> RemediationReport:
    """
    Plan + execute remediations for the supplied health snapshot.
    """
    report = RemediationReport()

    actions = list_actions(health_result)

    for action in actions:
        if action.action == "BLOCK_NEW_ENTRIES":
            report.blocked = True
            report.block_reasons.append(action.reason)
            # Audit the block decision too
            d = make_decision(
                decision_type="BLOCK_NEW_ENTRIES",
                decision="BLOCKED" if not dry_run else "DRY_RUN",
                reason=action.reason,
                actor=actor,
                inputs={"severity": action.severity},
                reversible=True,
                rollback_action="resume on next health OK",
                action_taken="set global block flag",
                result="ok",
            )
            write_audit_event(d, kind="trading")
            report.actions_taken.append({"action": action.action,
                                          "subject": action.subject,
                                          "ok": True, "dry_run": dry_run})
            continue

        # Cooldown
        if not _cooldown_ok(action.action, action.subject):
            report.skipped.append({"action": action.action,
                                    "subject": action.subject,
                                    "reason": "cooldown_active"})
            continue

        if dry_run:
            d = make_decision(
                decision_type=_decision_type_for(action.action),
                decision="DRY_RUN",
                reason=action.reason, actor=actor,
                inputs=action.__dict__,
                affected_symbols=[action.subject] if action.subject != "*" else [],
                reversible=True,
                action_taken="dry_run", result="ok",
            )
            write_audit_event(d, kind="trading")
            report.actions_taken.append({"action": action.action,
                                          "subject": action.subject,
                                          "ok": True, "dry_run": True})
            continue

        try:
            assert_paper_only(ALPACA_BASE_URL)
        except PaperOnlyViolation as e:
            report.skipped.append({"action": action.action,
                                    "subject": action.subject,
                                    "reason": f"paper_only: {e}"})
            continue

        handler = _DISPATCH.get(action.action)
        if not handler:
            report.skipped.append({"action": action.action,
                                    "subject": action.subject,
                                    "reason": "unknown action"})
            continue

        result = handler(action)
        _stamp_cooldown(action.action, action.subject)

        # v3.9.6: RECREATE_EXIT_PLAN is now REVERSIBLE (places OCO exit
        # orders; doesn't close position). PANIC_CLOSE_OPTIONS still
        # irreversible (market sells real positions).
        decision_status = "FAILED"
        if result.get("ok"):
            decision_status = "EXECUTED"
        elif result.get("skipped"):
            decision_status = "SKIPPED"

        d = make_decision(
            decision_type=_decision_type_for(action.action),
            decision=decision_status,
            reason=action.reason,
            actor=actor,
            inputs=action.__dict__,
            affected_symbols=[action.subject] if action.subject != "*" else [],
            risk_metrics={"severity": action.severity},
            reversible=action.action != "PANIC_CLOSE_OPTIONS",
            rollback_action=(
                "cancel OCO + place fresh" if action.action == "RECREATE_EXIT_PLAN"
                else ""
            ),
            action_taken=action.action,
            result=decision_status.lower(),
            errors=[] if result.get("ok") or result.get("skipped") else [str(result)],
        )
        write_audit_event(d, kind="trading")
        report.actions_taken.append({
            "action": action.action,
            "subject": action.subject,
            "ok": result.get("ok", False),
            "result": result,
        })

    return report


def _decision_type_for(action: str) -> str:
    """Map remediation action → autonomy DECISION_TYPES."""
    return {
        "CANCEL_STALE_ORDERS":  "CLEANUP_STALE_ORDERS",
        "RECREATE_EXIT_PLAN":   "RECREATE_EXIT_PLAN",
        "BLOCK_NEW_ENTRIES":    "BLOCK_NEW_ENTRIES",
        "PANIC_CLOSE_OPTIONS":  "PANIC_CLOSE_OPTIONS",
        "PAUSE_STRATEGY":       "PAUSE_STRATEGY",
        "RESUME_STRATEGY":      "RESUME_STRATEGY",
        "EMERGENCY_CLOSE":      "EMERGENCY_CLOSE",
    }.get(action, "CLEANUP_STALE_ORDERS")
