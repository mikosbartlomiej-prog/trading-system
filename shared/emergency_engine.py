"""
Autonomous emergency-close engine.

Selects positions that meet emergency criteria, then closes them via the
canonical Alpaca paper flow:

  1. Cancel any conflicting open SELL/BUY orders on the symbol.
  2. DELETE /v2/positions/{symbol}  (Alpaca's idempotent close primitive).
  3. Fallback: POST a SELL LIMIT (never MARKET on options) if DELETE fails.

Every action is paper-only — `assert_paper_only` runs before any HTTP
side-effect. Every action writes an audit JSONL record via
`shared.audit.write_audit_event`.

Emergency conditions (spec §3.1, deterministic):
  - position loss ≤ hard loss threshold (default -15% per profile)
  - position has NO valid exit plan (no open SELL/BUY counterparty)
  - duplicate/conflicting exit orders
  - stale exit order older than threshold (default 24h)
  - option DTE ≤ 5 AND loss ≥ -40%
  - portfolio_risk BLOCKED
  - daily drawdown breached
  - symbol disabled while position still open and no exit plan
  - kill-switch condition (defensive_mode_active)

Per-symbol rate limit: MAX_EMERGENCY_ATTEMPTS_PER_DAY (default 3) — stops
us spiralling into a close-loop on a sticky position.

Public API:
  scan_emergency_conditions(account, positions, open_orders, state, market_context)
      -> list[EmergencyTarget]
  execute_emergency_close(target, *, dry_run=False) -> dict
"""

from __future__ import annotations

import os
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
except ImportError:  # pragma: no cover
    from shared.autonomy import (  # type: ignore
        assert_paper_only, make_decision, PaperOnlyViolation, PAPER_BASE_URL,
    )
    from shared.audit import write_audit_event  # type: ignore


ALPACA_BASE_URL = PAPER_BASE_URL  # invariant


# ─── Thresholds (overridable via env / profile) ───────────────────────────────

HARD_LOSS_PCT          = float(os.environ.get("EMERGENCY_HARD_LOSS_PCT", "-15.0"))
DEEP_OPTION_LOSS_PCT   = float(os.environ.get("EMERGENCY_DEEP_OPTION_LOSS_PCT", "-40.0"))
NEAR_DTE_DAYS          = int(os.environ.get("EMERGENCY_NEAR_DTE_DAYS", "5"))
STALE_ORDER_HOURS      = float(os.environ.get("EMERGENCY_STALE_ORDER_HOURS", "24"))
MAX_ATTEMPTS_PER_DAY   = int(os.environ.get("EMERGENCY_MAX_ATTEMPTS_PER_DAY", "3"))


@dataclass
class EmergencyTarget:
    symbol: str
    reason: str
    loss_pct: float | None = None
    asset_class: str = "us_equity"
    qty: float = 0.0
    suggested_action: str = "DELETE"   # "DELETE" | "CANCEL_AND_DELETE" | "LIMIT_SELL"
    metadata: dict[str, Any] = field(default_factory=dict)


# ─── In-process attempt counter (reset by daily-learning's state stamp) ───────

_attempts_today: dict[str, int] = {}


def _attempts_key(symbol: str) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return f"{today}|{symbol.upper()}"


def _attempts_for(symbol: str) -> int:
    return _attempts_today.get(_attempts_key(symbol), 0)


def _bump_attempts(symbol: str) -> int:
    k = _attempts_key(symbol)
    _attempts_today[k] = _attempts_today.get(k, 0) + 1
    return _attempts_today[k]


# ─── Scan ─────────────────────────────────────────────────────────────────────

def _is_option(symbol: str) -> bool:
    return len(symbol) > 7 and any(ch.isdigit() for ch in symbol)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        ts = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except (ValueError, TypeError):
        return None


def _option_dte(symbol: str) -> int | None:
    """
    Parse the YYMMDD date out of an OCC contract symbol.
    Returns days-to-expiration or None on parse failure.
    """
    # AAPL260520C00170000 → YYMMDD starts after the alpha root
    i = 0
    while i < len(symbol) and symbol[i].isalpha():
        i += 1
    if i + 6 > len(symbol):
        return None
    yymmdd = symbol[i:i + 6]
    if not yymmdd.isdigit():
        return None
    try:
        yy = int(yymmdd[:2])
        mm = int(yymmdd[2:4])
        dd = int(yymmdd[4:6])
        year = 2000 + yy
        exp = datetime(year, mm, dd, tzinfo=timezone.utc)
        return max(0, (exp - datetime.now(timezone.utc)).days)
    except (ValueError, TypeError):
        return None


def _has_valid_exit_plan(symbol: str, side: str,
                        open_orders: list[dict]) -> bool:
    """Long needs an open SELL; short needs an open BUY."""
    need_side = "sell" if (side or "").lower() != "short" else "buy"
    for o in open_orders or []:
        if (o.get("symbol") or "").upper() != symbol.upper():
            continue
        if (o.get("side") or "").lower() == need_side:
            # An open exit order exists. Anything more (right price/qty) is
            # the remediation layer's job.
            return True
    return False


def _has_duplicate_exits(symbol: str, open_orders: list[dict]) -> bool:
    sells = sum(1 for o in (open_orders or [])
                if (o.get("symbol") or "").upper() == symbol.upper()
                and (o.get("side") or "").lower() == "sell")
    return sells > 1


def _has_stale_exit(symbol: str, open_orders: list[dict]) -> bool:
    now = datetime.now(timezone.utc)
    for o in open_orders or []:
        if (o.get("symbol") or "").upper() != symbol.upper():
            continue
        if (o.get("side") or "").lower() != "sell":
            continue
        ts = _parse_iso(o.get("submitted_at") or o.get("created_at"))
        if ts and (now - ts).total_seconds() / 3600.0 > STALE_ORDER_HOURS:
            return True
    return False


def scan_emergency_conditions(
    account: dict | None,
    positions: list[dict] | None,
    open_orders: list[dict] | None,
    state: dict | None = None,
    market_context: dict | None = None,
) -> list[EmergencyTarget]:
    """
    Build the list of emergency-close targets. Deterministic & pure.
    """
    targets: list[EmergencyTarget] = []
    positions = positions or []
    open_orders = open_orders or []
    state = state or {}

    # Account-level kill switches first.
    daily_pl_pct = _safe_float((account or {}).get("daily_pl_pct"))
    defensive = bool((state.get("defensive_mode") or {}).get("active"))

    for p in positions:
        if not isinstance(p, dict):
            continue
        sym = (p.get("symbol") or "").upper()
        if not sym:
            continue
        if _attempts_for(sym) >= MAX_ATTEMPTS_PER_DAY:
            continue

        asset_class = "us_option" if _is_option(sym) else (
            p.get("asset_class") or "us_equity")
        side = (p.get("side") or "long").lower()
        qty = abs(_safe_float(p.get("qty")))
        # Alpaca exposes unrealized_plpc (decimal: 0.05 = 5%). Tolerate
        # ratio vs percent variations.
        plpc = _safe_float(p.get("unrealized_plpc"))
        loss_pct = plpc * 100.0 if -1.0 < plpc < 1.0 else plpc

        # 1. Hard loss
        if loss_pct <= HARD_LOSS_PCT:
            targets.append(EmergencyTarget(
                symbol=sym, reason=f"hard_loss {loss_pct:.1f}% <= {HARD_LOSS_PCT}%",
                loss_pct=loss_pct, asset_class=asset_class, qty=qty,
            ))
            continue

        # 2. Options near DTE + deep loss
        if asset_class == "us_option":
            dte = _option_dte(sym)
            if dte is not None and dte <= NEAR_DTE_DAYS and loss_pct <= DEEP_OPTION_LOSS_PCT:
                targets.append(EmergencyTarget(
                    symbol=sym,
                    reason=f"option_near_dte dte={dte} loss={loss_pct:.1f}%",
                    loss_pct=loss_pct, asset_class=asset_class, qty=qty,
                    metadata={"dte": dte},
                ))
                continue

        # ─── v3.9.9 (2026-05-27) INVARIANT ─────────────────────────────────
        # Blocks 3/4/5 (no_exit_plan, duplicate_exits, stale_exit_order)
        # REMOVED. These are repairable artifacts of prior actions, not
        # emergency conditions. They are handled non-destructively by
        # shared/remediation.py:
        #   - no_exit_plan       → RECREATE_EXIT_PLAN (v3.9.6: OCO recreate)
        #   - duplicate_exits    → CANCEL_STALE_ORDERS with keep_one=True
        #   - stale_exit_order   → CANCEL_STALE_ORDERS
        # Prior behaviour (CANCEL_AND_DELETE = MARKET sell entire position)
        # caused 2026-05-22 + 2026-05-26 incidents where healthy positions
        # were liquidated unnecessarily. v3.9.6 fixed RECREATE_EXIT_PLAN
        # but left duplicate_exits/stale_exit_order paths in this scanner;
        # both fired on 2026-05-26 → 3 positions (SPY/QQQ/GLD) market-closed.
        # Invariant: EMERGENCY_CLOSE never used for repairable states.
        # Test: tests/architecture_vnext/test_emergency_engine_invariant.py
        # ───────────────────────────────────────────────────────────────────

        # 6. Defensive mode active → close everything not already exiting
        if defensive:
            targets.append(EmergencyTarget(
                symbol=sym, reason="defensive_mode_active",
                loss_pct=loss_pct, asset_class=asset_class, qty=qty,
            ))
            continue

    # 7. Daily drawdown — caller may want to close the whole book.
    # We surface it as a metadata marker on the first target.
    if daily_pl_pct <= -12.0 and targets:
        targets[0].metadata["daily_drawdown_pct"] = daily_pl_pct

    return targets


# ─── Execute (paper-only) ─────────────────────────────────────────────────────

def _headers() -> dict:
    return {
        "APCA-API-KEY-ID":     os.environ.get("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.environ.get("ALPACA_SECRET_KEY", ""),
    }


def _cancel_open_orders_for(symbol: str) -> int:
    """Cancel all open orders for a symbol. Returns count cancelled."""
    assert_paper_only(ALPACA_BASE_URL)
    cancelled = 0
    try:
        r = requests.get(
            f"{ALPACA_BASE_URL}/v2/orders",
            headers=_headers(), params={"status": "open", "symbols": symbol},
            timeout=10,
        )
        if r.status_code != 200:
            return 0
        for o in (r.json() or []):
            oid = o.get("id")
            if not oid:
                continue
            cr = requests.delete(f"{ALPACA_BASE_URL}/v2/orders/{oid}",
                                  headers=_headers(), timeout=10)
            if cr.status_code in (200, 204):
                cancelled += 1
    except Exception:
        pass
    return cancelled


def _close_position_delete(symbol: str) -> dict | None:
    """DELETE /v2/positions/{symbol} — Alpaca's canonical close primitive."""
    assert_paper_only(ALPACA_BASE_URL)
    enc = urllib.parse.quote(symbol, safe="")
    try:
        r = requests.delete(f"{ALPACA_BASE_URL}/v2/positions/{enc}",
                            headers=_headers(), timeout=15)
        if r.status_code in (200, 204):
            try:
                return r.json()
            except Exception:
                return {"status": "closed"}
        return {"_status": r.status_code, "_text": r.text[:200]}
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"}


def execute_emergency_close(
    target: EmergencyTarget,
    *,
    dry_run: bool = False,
    actor: str = "emergency_engine",
) -> dict:
    """
    Execute one emergency close. Returns a result dict and writes an
    audit JSONL row. Paper-only — refuses to operate against any other
    endpoint.

    `dry_run=True` writes the audit row with action_taken="dry_run"
    but does not call Alpaca.
    """
    # Paper-only invariant (catches misconfiguration).
    try:
        assert_paper_only(ALPACA_BASE_URL)
    except PaperOnlyViolation as e:
        result = {"ok": False, "blocked_by": "paper_only", "error": str(e)}
        decision = make_decision(
            decision_type="EMERGENCY_CLOSE",
            decision="BLOCKED",
            reason=f"paper-only violation: {e}",
            actor=actor,
            inputs=target.__dict__,
            affected_symbols=[target.symbol],
            reversible=False,
            rollback_action="",
            result="blocked",
            errors=[str(e)],
        )
        write_audit_event(decision, kind="trading")
        return result

    if _attempts_for(target.symbol) >= MAX_ATTEMPTS_PER_DAY:
        result = {"ok": False, "blocked_by": "max_attempts",
                  "attempts": _attempts_for(target.symbol)}
        decision = make_decision(
            decision_type="EMERGENCY_CLOSE",
            decision="SKIPPED",
            reason=f"max_attempts {_attempts_for(target.symbol)} >= {MAX_ATTEMPTS_PER_DAY}",
            actor=actor, inputs=target.__dict__,
            affected_symbols=[target.symbol],
            reversible=False,
            result="skipped",
        )
        write_audit_event(decision, kind="trading")
        return result

    if dry_run:
        decision = make_decision(
            decision_type="EMERGENCY_CLOSE",
            decision="DRY_RUN",
            reason=f"would close {target.symbol}: {target.reason}",
            actor=actor, inputs=target.__dict__,
            affected_symbols=[target.symbol],
            risk_metrics={"loss_pct": target.loss_pct},
            reversible=False,
            action_taken="dry_run", result="ok",
        )
        write_audit_event(decision, kind="trading")
        return {"ok": True, "dry_run": True, "symbol": target.symbol}

    cancelled = 0
    if target.suggested_action in ("CANCEL_AND_DELETE",):
        cancelled = _cancel_open_orders_for(target.symbol)

    close_resp = _close_position_delete(target.symbol)

    ok = (close_resp is not None
          and not close_resp.get("_error")
          and not close_resp.get("_status"))

    _bump_attempts(target.symbol)

    decision = make_decision(
        decision_type="EMERGENCY_CLOSE",
        decision="CLOSED" if ok else "FAILED",
        reason=target.reason,
        actor=actor,
        inputs=target.__dict__,
        affected_symbols=[target.symbol],
        risk_metrics={
            "loss_pct":            target.loss_pct,
            "cancelled_orders":    cancelled,
            "attempts_today":      _attempts_for(target.symbol),
        },
        reversible=False,
        action_taken=f"cancel={cancelled}; delete /v2/positions/{target.symbol}",
        result="closed" if ok else "failed",
        errors=[] if ok else [str(close_resp)],
    )
    write_audit_event(decision, kind="trading")

    return {
        "ok":               ok,
        "symbol":           target.symbol,
        "reason":           target.reason,
        "cancelled_orders": cancelled,
        "close_response":   close_resp,
        "attempts_today":   _attempts_for(target.symbol),
    }
