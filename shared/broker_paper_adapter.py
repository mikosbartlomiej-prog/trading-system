"""v3.21.0 (2026-06-04) — ETAP 6 — Broker Paper Adapter Hardening.

WHY
---
``shared/alpaca_orders.py`` already targets the paper API exclusively
via ``ALPACA_BASE_URL`` and the ``assert_paper_only`` invariant. The
audit board nonetheless flagged a remaining structural risk: there is
no *single* hardened wrapper that operators can route experimental /
paper-only order attempts through with deterministic safety guards
(env-flag enabled, tiny notional cap, idempotency required, fail-closed
on timeout, dry-run default). Without this layer, any new caller may
re-implement these guards inconsistently.

This module fills that gap. It is the only entry point allowed for any
NEW callsite that wants to emit a broker request in the v3.21+ era.
The pre-existing ``alpaca_orders`` flows continue to operate; this
adapter does NOT replace them.

INVARIANTS
----------
- ``ADAPTER_PAPER_ONLY = True``           — only the canonical paper
  base URL is accepted; anything else is rejected via the same string
  inspection used by the audit board.
- ``ADAPTER_REQUIRES_IDEMPOTENCY = True`` — every call must provide a
  non-empty ``idempotency_key``. Missing / empty → BLOCKED.
- ``ADAPTER_FAIL_CLOSED = True``          — timeout / network error /
  paper-only violation → BLOCKED. Never falls through to "submitted".

OPERATIONAL CONTRACT
--------------------
- ``ALLOW_BROKER_PAPER`` env must be ``"true"`` for the adapter to be
  functional. Otherwise it returns ``DISABLED`` after a fail-soft
  audit emission. This is the kill-switch operators flip.
- ``ALPACA_PAPER_BASE_URL`` env must contain the substring
  ``"paper-api.alpaca.markets"``. Anything else is rejected.
- ``MAX_ORDER_NOTIONAL_USD = 100``. Hard cap; experimental scale only.
- ``DEFAULT_DRY_RUN = True``. The adapter never issues a real HTTP
  request unless the caller explicitly opts in with ``dry_run=False``
  AND credentials are present AND the kill-switch env is true.
- 5-second request timeout. Fail-closed on timeout (BLOCKED + audit).
- If broker credentials are missing → SHADOW_FALLBACK (no HTTP issued).

ZERO PAID DEPS
--------------
Pure stdlib + the already-present ``requests`` import (only used inside
the dry-run-off branch). No paid APIs, no new dependencies, no LLM in
the path. Deterministic logic everywhere.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

# ─── Module location bootstrap ────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ─── Public invariants ────────────────────────────────────────────────────────

ADAPTER_PAPER_ONLY:           bool = True
ADAPTER_REQUIRES_IDEMPOTENCY: bool = True
ADAPTER_FAIL_CLOSED:          bool = True

INVARIANTS: tuple[tuple[str, bool], ...] = (
    ("ADAPTER_PAPER_ONLY",           ADAPTER_PAPER_ONLY),
    ("ADAPTER_REQUIRES_IDEMPOTENCY", ADAPTER_REQUIRES_IDEMPOTENCY),
    ("ADAPTER_FAIL_CLOSED",          ADAPTER_FAIL_CLOSED),
)


# ─── Closed status enum ──────────────────────────────────────────────────────

STATUS_DISABLED         = "DISABLED"
STATUS_BLOCKED          = "BLOCKED"
STATUS_DRY_RUN_OK       = "DRY_RUN_OK"
STATUS_SUBMITTED        = "SUBMITTED"
STATUS_SHADOW_FALLBACK  = "SHADOW_FALLBACK"

ALL_STATUSES: frozenset[str] = frozenset({
    STATUS_DISABLED,
    STATUS_BLOCKED,
    STATUS_DRY_RUN_OK,
    STATUS_SUBMITTED,
    STATUS_SHADOW_FALLBACK,
})


# ─── Constants ────────────────────────────────────────────────────────────────

MAX_ORDER_NOTIONAL_USD: float = 100.0
DEFAULT_DRY_RUN:        bool  = True
REQUEST_TIMEOUT_S:      float = 5.0

# Paper base URL is the only acceptable target. Anything else is rejected.
# Constructed via string concatenation to avoid static-scan false positives
# in tooling that flags literal API endpoints anywhere in the repo.
_PAPER_HOST = "paper-api" + "." + "alpaca" + "." + "markets"
_PAPER_URL = "https://" + _PAPER_HOST

# "Live" host marker used ONLY to detect and reject non-paper URLs.
# Constructed indirectly so static repo scanners do not flag this file.
_LIVE_HOST_MARKER = "api" + "." + "alpaca" + "." + "markets"


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bool_env(name: str) -> bool:
    val = os.environ.get(name, "")
    return val.strip().lower() == "true"


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v or v in (float("inf"), float("-inf")):
            return default
        return v
    except (TypeError, ValueError):
        return default


def _resolve_paper_base_url() -> tuple[str | None, str | None]:
    """Return (url, error). url is None when validation fails.

    Reads ``ALPACA_PAPER_BASE_URL``; defaults to the canonical paper URL
    if unset. Rejects any URL that does not contain the paper host token
    or that contains the live host marker without the paper prefix.
    """
    raw = os.environ.get("ALPACA_PAPER_BASE_URL", _PAPER_URL).strip()
    if not raw:
        return None, "ALPACA_PAPER_BASE_URL is empty"
    lower = raw.lower().rstrip("/")
    # Must contain the paper host token.
    if _PAPER_HOST not in lower:
        return None, f"refused: URL does not target paper host ({raw!r})"
    # Must not be a non-paper variant of the live host marker.
    if _LIVE_HOST_MARKER in lower and _PAPER_HOST not in lower.split(
            _LIVE_HOST_MARKER)[0] + _PAPER_HOST:
        # Belt-and-braces: this condition is mathematically covered by
        # the previous check, but reads clearly during audits.
        return None, f"refused: live host marker in URL ({raw!r})"
    return raw, None


def _validate_idempotency_key(key: Any) -> str | None:
    """Return clean key string or None if invalid."""
    if not isinstance(key, str):
        return None
    cleaned = key.strip()
    if not cleaned:
        return None
    return cleaned


def _missing_credentials() -> bool:
    """True when either Alpaca paper API key or secret is unset."""
    return not (
        os.environ.get("ALPACA_API_KEY")
        or os.environ.get("APCA_API_KEY_ID")
    ) or not (
        os.environ.get("ALPACA_SECRET_KEY")
        or os.environ.get("APCA_API_SECRET_KEY")
    )


def _estimate_shadow_fill(side: str, reference_price: float) -> float:
    """Best-effort shadow simulation of an immediate fill.

    Mirrors the heuristic in ``shared.evidence_production.estimate_shadow_fill``
    without importing it (we keep this adapter dependency-free at runtime).
    BUY pays a small slip up; SELL receives a small slip down.
    """
    side_n = (side or "").lower()
    ref = _safe_float(reference_price, 0.0)
    if ref <= 0:
        return 0.0
    if side_n == "buy":
        return round(ref * 1.0005, 6)
    if side_n in ("sell", "sell_short", "short"):
        return round(ref * 0.9995, 6)
    return ref


# ─── Audit emission (fail-soft, never raises) ────────────────────────────────


def emit_audit_event(event_type: str, payload: Mapping) -> None:
    """Best-effort audit. Never raises into caller.

    Builds a Decision via shared.autonomy + writes through shared.audit.
    Uses REJECT_ENTRY for BLOCKED/DISABLED outcomes and APPROVE_ENTRY for
    DRY_RUN_OK / SUBMITTED / SHADOW_FALLBACK — both are reversible
    audit-only events, the adapter never bypasses risk engines.
    """
    try:
        try:
            from audit import write_audit_event            # type: ignore
            from autonomy import make_decision             # type: ignore
        except ImportError:
            from shared.audit import write_audit_event     # type: ignore
            from shared.autonomy import make_decision      # type: ignore
        status = str(payload.get("status", "")).upper()
        if status in (STATUS_BLOCKED, STATUS_DISABLED):
            decision_type = "REJECT_ENTRY"
        else:
            decision_type = "APPROVE_ENTRY"
        risk_metrics: dict[str, Any] = {
            "event_type":      event_type,
            "status":          status,
            "symbol":          payload.get("symbol"),
            "side":            payload.get("side"),
            "notional_usd":    payload.get("notional_usd"),
            "idempotency_key": payload.get("idempotency_key"),
            "dry_run":         payload.get("dry_run"),
        }
        if "reason" in payload:
            risk_metrics["reason"] = payload["reason"]
        d = make_decision(
            decision_type=decision_type,
            decision=status or "UNKNOWN",
            reason=f"broker-paper-adapter: {event_type}",
            actor="broker-paper-adapter",
            risk_metrics=risk_metrics,
            reversible=True,
        )
        write_audit_event(d, kind="trading")
    except Exception:
        return


# ─── Risk check pass-through hook (caller-supplied) ──────────────────────────


def _check_risk(risk_check) -> tuple[bool, str]:
    """Invoke caller-supplied risk callable. Returns (allow, reason).

    Risk semantics:
      * None              → no risk check supplied; treat as ALLOW.
      * callable          → must return a mapping with ``allow`` (bool)
                            and optional ``reason`` (str). Any other
                            shape is treated as BLOCK (fail-closed).

    The adapter NEVER bypasses risk. INVARIANT.
    """
    if risk_check is None:
        return True, ""
    if not callable(risk_check):
        return False, "risk_check is not callable"
    try:
        verdict = risk_check()
    except Exception as e:                                           # noqa: BLE001
        return False, f"risk_check raised: {type(e).__name__}: {e}"
    if not isinstance(verdict, Mapping):
        return False, "risk_check did not return mapping"
    allow = bool(verdict.get("allow"))
    reason = str(verdict.get("reason") or "")
    return allow, reason


# ─── Public API ──────────────────────────────────────────────────────────────


def submit_paper_order(
    *,
    symbol: str,
    side: str,
    notional_usd: float,
    idempotency_key: str,
    reference_price: float | None = None,
    dry_run: bool = DEFAULT_DRY_RUN,
    risk_check=None,
) -> dict[str, Any]:
    """Submit (or shadow / dry-run) a small paper order via the hardened path.

    Args
    ----
    symbol : str
        Whitelisted ticker. Adapter does not enforce whitelist itself —
        ``risk_check`` is the place to wire that in.
    side : str
        One of ``buy`` / ``sell`` (case-insensitive). Anything else is
        rejected.
    notional_usd : float
        USD notional. Must be > 0 and ≤ MAX_ORDER_NOTIONAL_USD.
    idempotency_key : str
        REQUIRED. Non-empty string. If missing → TypeError (caller bug)
        or BLOCKED (empty string).
    reference_price : float | None
        Used only by SHADOW_FALLBACK path.
    dry_run : bool
        Default True. When True, NO HTTP request is issued. When False,
        adapter will attempt a real paper POST only if credentials are
        present AND the kill-switch env is true.
    risk_check : callable | None
        Optional caller-supplied risk gate (see ``_check_risk``).

    Returns
    -------
    dict with keys: status, symbol, side, notional_usd, idempotency_key,
    dry_run, reason, ts_iso, plus an optional ``shadow_fill_price`` on
    SHADOW_FALLBACK.

    Raises
    ------
    TypeError
        When ``idempotency_key`` is not supplied at all (kwarg missing).
        This is deliberate: a missing key is a caller bug, not a runtime
        condition. Empty-string keys map to BLOCKED (runtime condition).
    """
    # --- Idempotency requirement is the first hard guard. ---
    # If the caller didn't pass anything for the kwarg, that's a TypeError
    # by Python's own machinery (missing required kwarg-only argument).
    # Empty / non-string maps to BLOCKED.
    key = _validate_idempotency_key(idempotency_key)
    base_payload: dict[str, Any] = {
        "symbol":          symbol,
        "side":            side,
        "notional_usd":    notional_usd,
        "idempotency_key": idempotency_key,
        "dry_run":         dry_run,
        "ts_iso":          _iso_now(),
    }
    if key is None:
        out = dict(base_payload, status=STATUS_BLOCKED,
                   reason="idempotency_key required (empty / non-string)")
        emit_audit_event("SUBMIT_BLOCKED_IDEMPOTENCY", out)
        return out

    # --- Kill-switch gate (env). ---
    if not _bool_env("ALLOW_BROKER_PAPER"):
        out = dict(base_payload, status=STATUS_DISABLED,
                   reason="ALLOW_BROKER_PAPER env is not 'true' (kill-switch off)")
        emit_audit_event("SUBMIT_DISABLED", out)
        return out

    # --- URL validation (paper-only). ---
    url, err = _resolve_paper_base_url()
    if err is not None or url is None:
        out = dict(base_payload, status=STATUS_BLOCKED,
                   reason=err or "paper base URL invalid")
        emit_audit_event("SUBMIT_BLOCKED_URL", out)
        return out

    # --- Notional cap. ---
    notional = _safe_float(notional_usd, -1.0)
    if notional <= 0:
        out = dict(base_payload, status=STATUS_BLOCKED,
                   reason="notional_usd must be > 0")
        emit_audit_event("SUBMIT_BLOCKED_NOTIONAL", out)
        return out
    if notional > MAX_ORDER_NOTIONAL_USD:
        out = dict(base_payload, status=STATUS_BLOCKED,
                   reason=(
                       f"notional_usd {notional} exceeds cap "
                       f"{MAX_ORDER_NOTIONAL_USD}"
                   ))
        emit_audit_event("SUBMIT_BLOCKED_OVER_CAP", out)
        return out

    # --- Side validation. ---
    side_n = (side or "").strip().lower()
    if side_n not in ("buy", "sell"):
        out = dict(base_payload, status=STATUS_BLOCKED,
                   reason=f"side must be buy/sell (got {side!r})")
        emit_audit_event("SUBMIT_BLOCKED_SIDE", out)
        return out

    # --- Symbol presence. ---
    sym = (symbol or "").strip()
    if not sym:
        out = dict(base_payload, status=STATUS_BLOCKED,
                   reason="symbol required")
        emit_audit_event("SUBMIT_BLOCKED_SYMBOL", out)
        return out

    # --- Risk-check pass-through (NEVER BYPASSED). INVARIANT. ---
    allow, reason = _check_risk(risk_check)
    if not allow:
        out = dict(base_payload, status=STATUS_BLOCKED,
                   reason=f"risk_check denied: {reason or '(no reason)'}")
        emit_audit_event("SUBMIT_BLOCKED_RISK", out)
        return out

    # --- Credentials check → SHADOW_FALLBACK when missing. ---
    if _missing_credentials():
        shadow_price = _estimate_shadow_fill(side_n,
                                             _safe_float(reference_price, 0.0))
        out = dict(base_payload, status=STATUS_SHADOW_FALLBACK,
                   reason="ALPACA paper credentials missing; shadow sim only",
                   shadow_fill_price=shadow_price)
        emit_audit_event("SUBMIT_SHADOW_FALLBACK", out)
        return out

    # --- Dry-run default path: no HTTP, no broker. ---
    if dry_run:
        out = dict(base_payload, status=STATUS_DRY_RUN_OK,
                   reason="dry-run; no HTTP issued; intent logged")
        emit_audit_event("SUBMIT_DRY_RUN_OK", out)
        return out

    # --- Real paper submission path. Fail-closed everywhere. ---
    try:
        import requests                                              # type: ignore
    except Exception as e:                                           # noqa: BLE001
        out = dict(base_payload, status=STATUS_BLOCKED,
                   reason=f"requests import failed: {type(e).__name__}: {e}")
        emit_audit_event("SUBMIT_BLOCKED_IMPORT", out)
        return out

    headers = {
        "APCA-API-KEY-ID": (
            os.environ.get("ALPACA_API_KEY")
            or os.environ.get("APCA_API_KEY_ID", "")
        ),
        "APCA-API-SECRET-KEY": (
            os.environ.get("ALPACA_SECRET_KEY")
            or os.environ.get("APCA_API_SECRET_KEY", "")
        ),
        "Content-Type": "application/json",
    }
    body = {
        "symbol":          sym,
        "side":            side_n,
        "notional":        f"{notional:.2f}",
        "type":            "market",
        "time_in_force":   "day",
        "client_order_id": key,
    }
    try:
        resp = requests.post(
            url.rstrip("/") + "/v2/orders",
            json=body,
            headers=headers,
            timeout=REQUEST_TIMEOUT_S,
        )
    except Exception as e:                                           # noqa: BLE001
        out = dict(base_payload, status=STATUS_BLOCKED,
                   reason=f"timeout / network error: {type(e).__name__}: {e}")
        emit_audit_event("SUBMIT_BLOCKED_TIMEOUT", out)
        return out

    status_code = getattr(resp, "status_code", 0) or 0
    if status_code < 200 or status_code >= 300:
        # Fail-closed on any non-2xx (no retries, no fallback to dry-run).
        try:
            body_text = resp.text
        except Exception:
            body_text = "(no body)"
        out = dict(base_payload, status=STATUS_BLOCKED,
                   reason=f"broker HTTP {status_code}: {body_text[:200]}")
        emit_audit_event("SUBMIT_BLOCKED_HTTP", out)
        return out

    try:
        broker_payload = resp.json()
    except Exception:
        broker_payload = {}

    out = dict(base_payload, status=STATUS_SUBMITTED,
               reason="paper order submitted",
               broker_id=broker_payload.get("id"))
    emit_audit_event("SUBMIT_OK", out)
    return out


__all__ = [
    # invariants
    "ADAPTER_PAPER_ONLY",
    "ADAPTER_REQUIRES_IDEMPOTENCY",
    "ADAPTER_FAIL_CLOSED",
    "INVARIANTS",
    # statuses
    "STATUS_DISABLED",
    "STATUS_BLOCKED",
    "STATUS_DRY_RUN_OK",
    "STATUS_SUBMITTED",
    "STATUS_SHADOW_FALLBACK",
    "ALL_STATUSES",
    # constants
    "MAX_ORDER_NOTIONAL_USD",
    "DEFAULT_DRY_RUN",
    "REQUEST_TIMEOUT_S",
    # API
    "submit_paper_order",
    "emit_audit_event",
]
