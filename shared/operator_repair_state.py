"""v3.29 ETAP 1 (2026-06-16) — Operator manual-repair confirmation markers.

CONTAINMENT MODULE — read this before changing anything.

WHY THIS EXISTS
---------------
``shared/broker_repair_required.py`` quarantines a symbol after the
P13 retry budget is exhausted. The contract for clearing that
quarantine is: a *human operator* must physically check the Alpaca
dashboard, confirm that orphaned OCO legs / dust positions were
manually fixed, and then drop a marker file on disk. ONLY then is
``broker_repair_required.clear_repair`` allowed to remove the flag.

This module owns the operator-confirmation marker. It is the
canonical "the operator looked at the broker UI, did the work, and
took responsibility" data structure.

HARD INVARIANTS (do not break)
------------------------------
* This module NEVER imports ``alpaca_orders``.
* This module NEVER calls ``submit_order`` / ``place_order`` /
  ``safe_close`` / ``cancel_order`` / ``close_position``.
* This module NEVER makes network calls.
* This module NEVER auto-clears ``safe_mode``.
* This module NEVER mutates any "live trading" flag
  (``LIVE_TRADING``, ``ALLOW_BROKER_PAPER``, ``EDGE_GATE_ENABLED``).
* Writes are atomic (tmp file + ``os.replace`` + best-effort fsync).
* All markers live under ``learning-loop/operator_markers/``.
* ``does_not_execute_orders`` on every payload is forced to ``True``.
* ``source`` on every payload is forced to
  ``"OPERATOR_MANUAL_CONFIRMATION"``.

STANDING MARKERS (footer of dump / docs)
----------------------------------------
- ``EDGE_GATE_ENABLED=false``
- ``ALLOW_BROKER_PAPER=false``
- ``LIVE_TRADING_UNSUPPORTED``
- ``NO_ORDER_PLACEMENT``
- ``NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE``
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Standing invariants (asserted by tests) ───────────────────────────────────
LIVE_TRADING_UNSUPPORTED = True
NO_ORDER_PLACEMENT = True
NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE = True
EDGE_GATE_ENABLED = False
ALLOW_BROKER_PAPER = False

MARKER_SOURCE = "OPERATOR_MANUAL_CONFIRMATION"

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _markers_dir() -> Path:
    """Where operator-repair markers live on disk.

    Honours ``OPERATOR_MARKERS_DIR`` for tests so they can point at a
    tmp directory without touching production state.
    """
    env = os.environ.get("OPERATOR_MARKERS_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "operator_markers"


def _audit_dir() -> Path:
    env = os.environ.get("AUDIT_TRADING_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "journal" / "autonomy"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OperatorRepairConfirmation:
    """Frozen record of a single operator-confirmed repair.

    Every field except the four "always-set" ones is supplied by the
    operator via :func:`write_marker`. The four invariants
    (``source``, ``does_not_execute_orders``, plus the dataclass being
    frozen) are forced by :func:`_normalize` before persistence so
    callers cannot accidentally subvert the contract.
    """

    symbol: str
    incident_type: str
    dashboard_checked: bool
    open_orders_checked: bool
    stale_oco_cancelled_by_operator: str  # "true" | "false" | "unknown"
    position_closed_by_operator: str       # "true" | "false" | "unknown"
    final_position_state: str
    final_open_orders_state: str
    equity_checked: bool
    operator_note: str
    timestamp_iso: str
    source: str = MARKER_SOURCE
    does_not_execute_orders: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "OperatorRepairConfirmation":
        return cls(
            symbol=str(raw.get("symbol", "")),
            incident_type=str(raw.get("incident_type", "")),
            dashboard_checked=bool(raw.get("dashboard_checked", False)),
            open_orders_checked=bool(raw.get("open_orders_checked", False)),
            stale_oco_cancelled_by_operator=str(raw.get("stale_oco_cancelled_by_operator", "unknown")),
            position_closed_by_operator=str(raw.get("position_closed_by_operator", "unknown")),
            final_position_state=str(raw.get("final_position_state", "")),
            final_open_orders_state=str(raw.get("final_open_orders_state", "")),
            equity_checked=bool(raw.get("equity_checked", False)),
            operator_note=str(raw.get("operator_note", "")),
            timestamp_iso=str(raw.get("timestamp_iso", "")),
            source=MARKER_SOURCE,                   # ALWAYS forced
            does_not_execute_orders=True,            # ALWAYS forced
        )


def _normalize(payload: OperatorRepairConfirmation) -> OperatorRepairConfirmation:
    """Force the two invariants regardless of caller input."""
    return replace(
        payload,
        source=MARKER_SOURCE,
        does_not_execute_orders=True,
    )


# ── Path helpers ──────────────────────────────────────────────────────────────

def _marker_path(symbol: str, date_iso: Optional[str] = None) -> Path:
    """Canonical marker filename for ``symbol`` on ``date_iso``."""
    safe_sym = str(symbol).replace("/", "_").replace(" ", "_")
    d = date_iso or _today_iso_date()
    return _markers_dir() / f"{safe_sym}_{d}.json"


def _latest_marker_for(symbol: str) -> Optional[Path]:
    """Return the newest marker path for ``symbol`` if any exists."""
    sym = str(symbol).replace("/", "_").replace(" ", "_")
    d = _markers_dir()
    if not d.exists():
        return None
    candidates = sorted(
        (p for p in d.glob(f"{sym}_*.json") if p.is_file()),
        key=lambda p: p.name,
        reverse=True,
    )
    return candidates[0] if candidates else None


# ── Audit (no network, no shared.audit dependency to keep this leaf-pure) ─────

def _append_audit(event: dict) -> None:
    """Best-effort audit JSONL append.

    Fail-soft: any I/O error is swallowed (we'd rather lose an audit
    row than crash an operator-facing CLI).
    """
    try:
        d = _audit_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{_today_iso_date()}.jsonl"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True, default=str) + "\n")
    except OSError:
        return


# ── Public API ────────────────────────────────────────────────────────────────

def write_marker(payload: OperatorRepairConfirmation) -> Path:
    """Atomically persist an operator-confirmation marker.

    HARD: this function does *nothing* beyond writing a JSON file +
    appending one audit row. No broker call. No safe_mode mutation.
    No flag flipping. Callers asking for any of those have to invoke
    a different module — this one will refuse to do it.
    """
    norm = _normalize(payload)
    if not norm.symbol:
        raise ValueError("write_marker: symbol cannot be empty")
    if not norm.timestamp_iso:
        raise ValueError("write_marker: timestamp_iso cannot be empty")

    path = _marker_path(norm.symbol)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(norm.to_dict(), fh, indent=2, sort_keys=True)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp, path)

    _append_audit({
        "decision_type":   "OPERATOR_REPAIR_MARKER_WRITTEN",
        "actor":           "operator_repair_state",
        "symbol":          norm.symbol,
        "incident_type":   norm.incident_type,
        "marker_path":     str(path),
        "source":          MARKER_SOURCE,
        "does_not_execute_orders": True,
        "ts_iso":          _now_iso(),
        "reversible":      True,
        "status":          "placed",
    })
    return path


def load_marker(symbol: str, date_iso: Optional[str] = None) -> Optional[OperatorRepairConfirmation]:
    """Return the most-recent marker for ``symbol``.

    When ``date_iso`` is supplied the exact dated file is read. When
    omitted, the newest marker for the symbol is returned (None if no
    markers exist).
    """
    if not symbol:
        return None
    path = _marker_path(symbol, date_iso) if date_iso else _latest_marker_for(symbol)
    if path is None or not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return OperatorRepairConfirmation.from_dict(raw)
    except Exception:
        return None


def list_markers() -> dict[str, OperatorRepairConfirmation]:
    """Return mapping symbol -> latest marker payload."""
    out: dict[str, OperatorRepairConfirmation] = {}
    d = _markers_dir()
    if not d.exists():
        return out
    for p in sorted(d.glob("*.json"), key=lambda x: x.name, reverse=True):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        try:
            payload = OperatorRepairConfirmation.from_dict(raw)
        except Exception:
            continue
        # Keep the first (newest by filename) per symbol.
        if payload.symbol and payload.symbol not in out:
            out[payload.symbol] = payload
    return out


def has_repair_confirmation(symbol: str, *, since_iso: Optional[str] = None) -> bool:
    """Return True iff a marker for ``symbol`` exists and is fresh.

    When ``since_iso`` is supplied, the marker's ``timestamp_iso``
    must be >= ``since_iso`` to count. This lets a quarantine that
    started at T0 only be cleared by a marker dated >= T0.
    """
    payload = load_marker(symbol)
    if payload is None:
        return False
    if not since_iso:
        return True
    try:
        marker_ts = datetime.fromisoformat(str(payload.timestamp_iso).replace("Z", "+00:00"))
        since_ts = datetime.fromisoformat(str(since_iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        # Bad timestamp on either side → treat as "not fresh enough".
        return False
    return marker_ts >= since_ts


# ── Standing-marker accessor (consumed by tests + docs builders) ──────────────

def standing_markers() -> list[str]:
    return [
        "EDGE_GATE_ENABLED=false",
        "ALLOW_BROKER_PAPER=false",
        "LIVE_TRADING_UNSUPPORTED",
        "NO_ORDER_PLACEMENT",
        "NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE",
    ]


__all__ = [
    "MARKER_SOURCE",
    "OperatorRepairConfirmation",
    "write_marker",
    "load_marker",
    "list_markers",
    "has_repair_confirmation",
    "standing_markers",
    # invariants (read-only constants)
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE",
    "EDGE_GATE_ENABLED",
    "ALLOW_BROKER_PAPER",
]
