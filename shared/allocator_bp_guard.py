"""
shared/allocator_bp_guard.py — ETAP 3 of 2026-06-07 incident response.

PROBLEM (2026-06-05):
    8 BUYs ALL rejected by Alpaca. Root cause: 2026-06-04 placed 8 BUYs that
    consumed buying power; 2026-06-05 allocator did not check current BP
    before re-submitting fresh BUYs. Each call hit Alpaca 403
    "insufficient buying power".

CONTRACT:
    Pre-execution gate. Walks the BUY notionals in priority order and drops
    the tail orders whose cumulative notional would exceed currently-available
    buying power. Also enforces a soft exposure cap read from
    config/aggressive_profile.json::capital.max_gross_exposure (deferred
    orders flagged with reason="EXPOSURE_CAP" if the cap would be breached).

INVARIANTS (verified by tests + audit):
    BP_GUARD_NEVER_RAISES_LIMITS = True
        This module is deterministic and ONLY drops orders. It NEVER raises
        a risk limit, exposure cap, or buying-power floor. It does not
        modify size, price, or trading-window decisions.

    BP_GUARD_FAIL_SOFT_ON_DATA_UNAVAILABLE = True
        If account_status is missing/None/0, EVERY order is allowed through
        and the returned dict carries warning="BP_DATA_UNAVAILABLE". The
        downstream risk_officer + portfolio_risk gates will still catch
        a genuinely BP-starved order; this module is the FIRST line of
        defense, not the only one.

EMITS:
    audit JSONL line via shared.audit.write_audit_event(..., kind="trading")
    with decision_type-equivalent record "V322_BP_GUARD" carrying projected
    vs available numbers, deferred symbols, and reasons.

CALLERS:
    shared/allocator.py::AccountAwareAllocator.execute_orders — invoked
    BEFORE the per-order loop. Deferred orders are mutated to
    status="deferred_bp" so they surface in execution.json results.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# ─── Invariants (test-asserted) ───────────────────────────────────────────────

BP_GUARD_NEVER_RAISES_LIMITS: bool = True
BP_GUARD_FAIL_SOFT_ON_DATA_UNAVAILABLE: bool = True


_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROFILE_PATH = _REPO_ROOT / "config" / "aggressive_profile.json"

# Fallback if profile unavailable. Matches the v3.0 aggressive_profile.json
# capital.max_gross_exposure default — NEVER above it; we may only be more
# conservative. Read at call time so tests can override.
_FALLBACK_MAX_GROSS = 1.50


def _load_max_gross_exposure() -> float:
    """
    Read max_gross_exposure from the aggressive profile. Fail-soft fallback
    to the historical default (1.50). Never raises.
    """
    try:
        with open(_PROFILE_PATH, encoding="utf-8") as f:
            prof = json.load(f)
        cap = prof.get("capital", {}).get("max_gross_exposure")
        if isinstance(cap, (int, float)) and cap > 0:
            return float(cap)
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        pass
    return float(_FALLBACK_MAX_GROSS)


def _notional(order: dict) -> float:
    """
    Best-effort notional for a BUY order.

    Allocator plan dicts have:
      target_value  — the dollar target for the resulting position
      current_value — what we already hold (for ramping into an existing pos)
      delta         — target_value - current_value (the actual BP demand)

    For NEW positions (current_value == 0) delta == target_value. For
    add-on BUYs we charge only the delta against BP (already-deployed
    capital does not double-count). Defensive: never negative.
    """
    delta = order.get("delta")
    if isinstance(delta, (int, float)) and delta > 0:
        return float(delta)
    target = order.get("target_value")
    if isinstance(target, (int, float)) and target > 0:
        current = order.get("current_value") or 0
        try:
            current = float(current)
        except (TypeError, ValueError):
            current = 0.0
        return max(0.0, float(target) - current)
    # size_usd is sometimes set by alpaca_orders callers
    size_usd = order.get("size_usd")
    if isinstance(size_usd, (int, float)) and size_usd > 0:
        return float(size_usd)
    return 0.0


def _action(order: dict) -> str:
    return str(order.get("action", "")).upper()


def _exposure_from_positions(positions: list[dict] | None) -> float:
    """
    Gross dollar exposure of currently-open positions (sum of abs(market_value)).
    Pending GTC orders are added by `pending_gtc_notional` separately.
    """
    if not positions:
        return 0.0
    total = 0.0
    for p in positions:
        mv = p.get("market_value")
        if mv is None:
            mv = p.get("notional", 0)
        try:
            total += abs(float(mv or 0))
        except (TypeError, ValueError):
            continue
    return total


def _audit_v322_bp_guard(record: dict) -> None:
    """
    Emit audit JSONL. Fail-soft: never raises, never blocks the gate.
    """
    try:
        try:
            from audit import write_audit_event  # type: ignore
        except ImportError:
            from shared.audit import write_audit_event  # type: ignore
        write_audit_event(record, kind="trading")
    except Exception as e:  # noqa: BLE001  fail-soft contract
        # Last-ditch: never crash execute_orders because audit IO failed.
        print(f"  [allocator_bp_guard] audit emit failed (fail-soft): {e}")


def check_buying_power_pre_execution(
    orders: list[dict],
    account_status: dict | None,
    open_positions: list[dict] | None = None,
    *,
    pending_gtc_notional: float = 0.0,
    max_gross_exposure: float | None = None,
    emit_audit: bool = True,
) -> dict:
    """
    Walk BUY notionals in input order (which already reflects allocator
    priority: BIG moves first per execute_orders' sort) and accept orders
    while cumulative_notional <= available_bp AND total exposure would
    remain under the gross exposure cap. Drop the tail into deferred_orders.

    NON-BUY orders (REDUCE / EXIT / HOLD / SELL) are PASSED THROUGH
    unchanged — they FREE capital, never consume it.

    PARAMETERS:
        orders               — list of allocator order dicts (mixed actions)
        account_status       — output of shared.risk_guards.get_account_status
                                expected keys: equity, buying_power
                                If None / empty / zero → fail-soft (warning)
        open_positions       — output of shared.risk_guards.get_open_positions
                                Used for current gross exposure calc.
        pending_gtc_notional — caller-supplied: dollar value of GTC orders
                                still resting on Alpaca (not yet filled).
                                Counts toward exposure cap. Default 0.
        max_gross_exposure   — float multiplier of equity. If None, read from
                                config/aggressive_profile.json. We NEVER raise
                                this above what's in the profile (test-asserted).
        emit_audit           — if False, skip JSONL emit (used by tests).

    RETURNS dict {
        allowed_orders:               list[dict]  passed-through
        deferred_orders:              list[dict]  mutated with deferred fields
        total_requested_notional:     float       sum of all BUY notionals
        total_available_bp:           float       account_status.buying_power
        total_open_exposure:          float       positions + pending GTC
        reason:                       str         human summary
        warning:                      str | None  set when BP data unavailable
        guard_invariants:             dict        BP_GUARD_NEVER_RAISES_LIMITS etc.
    }
    """
    orders = list(orders or [])
    open_positions = list(open_positions or [])

    invariants = {
        "BP_GUARD_NEVER_RAISES_LIMITS": BP_GUARD_NEVER_RAISES_LIMITS,
        "BP_GUARD_FAIL_SOFT_ON_DATA_UNAVAILABLE": BP_GUARD_FAIL_SOFT_ON_DATA_UNAVAILABLE,
    }

    # ── Partition + tally ─────────────────────────────────────────────────
    buys: list[dict] = []
    non_buys: list[dict] = []
    for o in orders:
        if _action(o) == "BUY":
            buys.append(o)
        else:
            non_buys.append(o)

    total_requested = sum(_notional(o) for o in buys)

    # ── Fail-soft on unavailable account data ─────────────────────────────
    def _safe_float(v: Any) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    bp_unavailable = (
        not account_status
        or not isinstance(account_status, dict)
        or _safe_float(account_status.get("buying_power", 0)) <= 0
        or _safe_float(account_status.get("equity", 0)) <= 0
    )
    if bp_unavailable:
        out = {
            "allowed_orders":            list(orders),
            "deferred_orders":           [],
            "total_requested_notional":  round(total_requested, 2),
            "total_available_bp":        0.0,
            "total_open_exposure":       0.0,
            "reason":                    "fail_soft: account_status unavailable; all orders passed through",
            "warning":                   "BP_DATA_UNAVAILABLE",
            "guard_invariants":          invariants,
        }
        if emit_audit:
            _audit_v322_bp_guard({
                "decision_type":            "V322_BP_GUARD",
                "decision":                 "PASS_THROUGH_FAIL_SOFT",
                "reason":                   out["reason"],
                "actor":                    "allocator-bp-guard",
                "warning":                  "BP_DATA_UNAVAILABLE",
                "total_requested_notional": out["total_requested_notional"],
                "total_available_bp":       0.0,
                "total_open_exposure":      0.0,
                "n_allowed":                len(out["allowed_orders"]),
                "n_deferred":               0,
            })
        return out

    available_bp = _safe_float(account_status.get("buying_power", 0))
    equity = _safe_float(account_status.get("equity", 0))

    # Exposure cap: max_gross_exposure × equity
    if max_gross_exposure is None:
        max_gross_exposure = _load_max_gross_exposure()
    else:
        # NEVER raise above profile setting. If caller passes a higher value
        # than the profile, clamp DOWN to the profile (invariant).
        try:
            profile_cap = _load_max_gross_exposure()
            if float(max_gross_exposure) > profile_cap:
                max_gross_exposure = profile_cap
        except (TypeError, ValueError):
            max_gross_exposure = _load_max_gross_exposure()
    exposure_cap_usd = max(0.0, float(max_gross_exposure) * equity)

    current_exposure = _exposure_from_positions(open_positions)
    try:
        pending_gtc = max(0.0, float(pending_gtc_notional or 0))
    except (TypeError, ValueError):
        pending_gtc = 0.0
    total_open_exposure = current_exposure + pending_gtc

    # ── Walk BUYs, allow while constraints hold ───────────────────────────
    allowed: list[dict] = []
    deferred: list[dict] = []
    cumulative_bp = 0.0
    cumulative_new_exposure = 0.0
    first_bp_breach: bool = True
    first_cap_breach: bool = True

    # Preserve non-BUY orders FIRST (they free capital — never deferred).
    allowed.extend(non_buys)

    for o in buys:
        n = _notional(o)
        if n <= 0:
            # Zero-notional BUY = HOLD effectively; allow through.
            allowed.append(o)
            continue

        # 1. Buying-power test
        projected_bp = cumulative_bp + n
        if projected_bp > available_bp:
            o = dict(o)  # copy so we don't surprise the caller
            o["status"] = "deferred_bp"
            o["deferred_reason"] = "INSUFFICIENT_BP_PROJECTED"
            o["bp_projected"] = round(projected_bp, 2)
            o["bp_available"] = round(available_bp, 2)
            deferred.append(o)
            if first_bp_breach:
                first_bp_breach = False
            continue

        # 2. Exposure-cap test
        projected_exposure = total_open_exposure + cumulative_new_exposure + n
        if projected_exposure > exposure_cap_usd:
            o = dict(o)
            o["status"] = "deferred_bp"
            o["deferred_reason"] = "EXPOSURE_CAP"
            o["exposure_projected"] = round(projected_exposure, 2)
            o["exposure_cap_usd"] = round(exposure_cap_usd, 2)
            deferred.append(o)
            if first_cap_breach:
                first_cap_breach = False
            continue

        cumulative_bp = projected_bp
        cumulative_new_exposure += n
        allowed.append(o)

    if deferred:
        reasons = sorted({d.get("deferred_reason", "") for d in deferred if d.get("deferred_reason")})
        reason = f"deferred {len(deferred)} BUY(s): {','.join(reasons)}"
    else:
        reason = "all BUYs fit available BP + exposure cap"

    out = {
        "allowed_orders":            allowed,
        "deferred_orders":           deferred,
        "total_requested_notional":  round(total_requested, 2),
        "total_available_bp":        round(available_bp, 2),
        "total_open_exposure":       round(total_open_exposure, 2),
        "reason":                    reason,
        "warning":                   None,
        "guard_invariants":          invariants,
        # Extra diagnostics — useful in tests + execution.json results
        "exposure_cap_usd":          round(exposure_cap_usd, 2),
        "max_gross_exposure":        float(max_gross_exposure),
        "n_buys_input":              len(buys),
        "n_buys_allowed":            len(allowed) - len(non_buys),
        "n_buys_deferred":           len(deferred),
        "n_non_buy_passthrough":     len(non_buys),
    }

    if emit_audit:
        _audit_v322_bp_guard({
            "decision_type":            "V322_BP_GUARD",
            "decision":                 "ENFORCE" if deferred else "ALLOW_ALL",
            "reason":                   reason,
            "actor":                    "allocator-bp-guard",
            "warning":                  None,
            "total_requested_notional": out["total_requested_notional"],
            "total_available_bp":       out["total_available_bp"],
            "total_open_exposure":      out["total_open_exposure"],
            "exposure_cap_usd":         out["exposure_cap_usd"],
            "max_gross_exposure":       out["max_gross_exposure"],
            "n_allowed":                len(allowed),
            "n_deferred":               len(deferred),
            "deferred_symbols":         [d.get("symbol") for d in deferred],
            "deferred_reasons":         [d.get("deferred_reason") for d in deferred],
        })

    return out
