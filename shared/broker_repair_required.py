"""v3.28 ETAP 4 (2026-06-16) — Per-symbol broker-repair-required state.

CONTAINMENT MODULE — read this before changing anything.

WHY THIS EXISTS
---------------
On 2026-06-15 the exit-monitor / safe_close path entered an infinite
retry loop against Alpaca paper crypto for AVAXUSD: 67+ identical
sell-to-close attempts in ~5.5h, each returning HTTP 403
``insufficient balance for AVAX``. No backoff. No quarantine. The
incident_pattern_detector P13 rule fired 10 times and entered
safe_mode 5 times, but safe_mode never made it into runtime_state
(separate writer bug) so the gate never activated. Allocator was
still free to deploy fresh capital.

This module is the per-symbol "stop trying, operator must repair"
state, completely orthogonal to safe_mode. It is meant to be
checked by every code path that submits sell/buy orders. When a
symbol is marked, all autonomous broker calls for that symbol
SKIP until an operator-confirmed marker file exists.

HARD INVARIANTS (do not break)
------------------------------
* This module NEVER imports ``alpaca_orders``.
* This module NEVER calls ``submit_order`` / ``place_order`` /
  ``safe_close`` / ``cancel_order`` / ``close_position``.
* This module NEVER makes network calls.
* ``clear_repair`` REFUSES to clear unless an operator marker file
  is present on disk. There is no in-process auto-clear path.
* ``save_state`` is atomic (tmp file + ``os.replace`` + ``fsync``).
* All writes go to ``learning-loop/broker_repair_required_latest.json``.

PUBLIC API
----------
``load_state() -> dict[str, BrokerRepairRequired]``
    Read the current state. Returns ``{}`` if the file is missing.

``save_state(state) -> Path``
    Atomically persist the given mapping. Returns the JSON path.

``mark_repair_required(symbol, incident_type=, error=, **kw) -> BrokerRepairRequired``
    Add or update the entry for ``symbol``. Increments
    ``failed_attempts``. Appends an audit JSONL row.

``is_repair_required(symbol) -> bool``
    Cheap point-lookup, used as a precondition by the retry path
    inside the exit-monitor / safe_close caller.

``get_blocked_symbols() -> set[str]``
    All symbols currently flagged.

``clear_repair(symbol, marker_path) -> bool``
    Refuses unless the operator-confirmed marker file exists.
    Audit row emitted on clear.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Module constants (spec §TASK 1) ───────────────────────────────────────────

#: How many consecutive failed broker close attempts the retry path is
#: allowed to perform before this symbol gets quarantined.
P13_RETRY_BUDGET: int = 3

#: Backoff schedule between attempts 1→2, 2→3, 3→4 (in seconds).
#: After the 3rd failure the symbol must be marked repair-required.
P13_RETRY_BACKOFF_SECONDS: tuple[int, int, int] = (60, 300, 1800)

#: safe_mode dedupe window used by the retry path to avoid spamming
#: identical SAFE_MODE_ENTERED events when the same incident keeps
#: hitting the same symbol.
SAFE_MODE_DEDUPE_WINDOW_SECONDS: int = 600


# ── Storage paths ─────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _state_path() -> Path:
    """Where the broker_repair_required state lives on disk.

    Honours ``BROKER_REPAIR_REQUIRED_PATH`` for tests so they can point
    at a tmp directory without touching production state.
    """
    env = os.environ.get("BROKER_REPAIR_REQUIRED_PATH")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "broker_repair_required_latest.json"


def _audit_dir() -> Path:
    env = os.environ.get("AUDIT_TRADING_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "journal" / "autonomy"


def _today_iso_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BrokerRepairRequired:
    """Per-symbol "do not autonomously call broker for this symbol" record.

    Frozen so callers cannot mutate in place — every update goes through
    ``mark_repair_required`` which writes a fresh instance and persists.
    """

    symbol: str
    incident_type: str
    first_seen_iso: str
    last_seen_iso: str
    failed_attempts: int
    last_error: str
    manual_action_required: str
    allowed_next_actions: tuple[str, ...]
    safe_mode_reason: str
    retry_after_iso: Optional[str] = None
    broker_calls_blocked_until_iso: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "symbol":                          self.symbol,
            "incident_type":                   self.incident_type,
            "first_seen_iso":                  self.first_seen_iso,
            "last_seen_iso":                   self.last_seen_iso,
            "failed_attempts":                 int(self.failed_attempts),
            "last_error":                      self.last_error,
            "manual_action_required":          self.manual_action_required,
            "allowed_next_actions":            list(self.allowed_next_actions),
            "safe_mode_reason":                self.safe_mode_reason,
            "retry_after_iso":                 self.retry_after_iso,
            "broker_calls_blocked_until_iso":  self.broker_calls_blocked_until_iso,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "BrokerRepairRequired":
        actions = raw.get("allowed_next_actions") or ()
        if isinstance(actions, list):
            actions = tuple(str(a) for a in actions)
        return cls(
            symbol=str(raw.get("symbol", "")),
            incident_type=str(raw.get("incident_type", "")),
            first_seen_iso=str(raw.get("first_seen_iso", "")),
            last_seen_iso=str(raw.get("last_seen_iso", "")),
            failed_attempts=int(raw.get("failed_attempts", 0) or 0),
            last_error=str(raw.get("last_error", "")),
            manual_action_required=str(raw.get("manual_action_required", "")),
            allowed_next_actions=tuple(actions),
            safe_mode_reason=str(raw.get("safe_mode_reason", "")),
            retry_after_iso=raw.get("retry_after_iso"),
            broker_calls_blocked_until_iso=raw.get("broker_calls_blocked_until_iso"),
        )


# ── State I/O ─────────────────────────────────────────────────────────────────

def load_state() -> dict[str, BrokerRepairRequired]:
    """Read the on-disk state.

    Returns an empty dict if the file is missing or unreadable. Any
    parse error returns ``{}`` (NEVER raises) so a corrupted state
    cannot crash the trading loop — callers will fall back to "no
    quarantine" which the allocator gate fails CLOSED on anyway.
    """
    path = _state_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(raw, dict):
        return {}

    out: dict[str, BrokerRepairRequired] = {}
    entries = raw.get("entries") if "entries" in raw else raw
    if not isinstance(entries, dict):
        return {}
    for sym, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        try:
            out[str(sym)] = BrokerRepairRequired.from_dict(entry)
        except Exception:
            # Per-entry parse failure — skip this symbol but keep loading.
            continue
    return out


def save_state(state: dict[str, BrokerRepairRequired]) -> Path:
    """Atomically write the given state mapping.

    Implementation: write to ``<path>.tmp``, fsync, then ``os.replace``
    to swap. ``os.replace`` is atomic on POSIX. Returns the canonical
    path that now holds the new state.
    """
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "v3.28",
        "updated_at":     _now_iso(),
        "entries": {
            sym: entry.to_dict() if isinstance(entry, BrokerRepairRequired) else dict(entry)
            for sym, entry in state.items()
        },
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            # fsync best-effort — some filesystems (test tmpfs) reject it.
            pass
    os.replace(tmp, path)
    return path


# ── Audit emission (no shared.audit dependency to keep this leaf-pure) ────────

def _append_audit(event: dict) -> None:
    """Append a single audit row to today's journal/autonomy JSONL.

    Fail-soft: any I/O error is swallowed (we'd rather lose an audit row
    than crash the trading loop). The audit module proper has the same
    contract for its own writes.
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

def mark_repair_required(
    symbol: str,
    *,
    incident_type: str,
    error: str = "",
    manual_action_required: str = "",
    allowed_next_actions: tuple[str, ...] = ("operator_marker_required",),
    safe_mode_reason: str = "",
    retry_after_iso: Optional[str] = None,
    broker_calls_blocked_until_iso: Optional[str] = None,
) -> BrokerRepairRequired:
    """Add or update the repair-required entry for ``symbol``.

    Idempotent: calling repeatedly for the same symbol just increments
    ``failed_attempts`` and refreshes ``last_seen_iso`` + ``last_error``.

    Every call appends an audit row of type
    ``REPAIR_REQUIRED_MARK_SET`` (first time) or
    ``REPAIR_REQUIRED_MARK_UPDATED`` (subsequent).
    """
    if not symbol:
        raise ValueError("mark_repair_required: symbol cannot be empty")

    sym = str(symbol)
    state = load_state()
    now = _now_iso()
    prev = state.get(sym)

    if prev is None:
        attempts = 1
        first_seen = now
        event_type = "REPAIR_REQUIRED_MARK_SET"
    else:
        attempts = int(prev.failed_attempts) + 1
        first_seen = prev.first_seen_iso or now
        event_type = "REPAIR_REQUIRED_MARK_UPDATED"

    entry = BrokerRepairRequired(
        symbol=sym,
        incident_type=str(incident_type),
        first_seen_iso=first_seen,
        last_seen_iso=now,
        failed_attempts=attempts,
        last_error=str(error or ""),
        manual_action_required=str(manual_action_required or ""),
        allowed_next_actions=tuple(allowed_next_actions or ()),
        safe_mode_reason=str(safe_mode_reason or ""),
        retry_after_iso=retry_after_iso,
        broker_calls_blocked_until_iso=broker_calls_blocked_until_iso,
    )
    state[sym] = entry
    save_state(state)

    _append_audit({
        "decision_type":  event_type,
        "actor":          "broker_repair_required",
        "symbol":         sym,
        "incident_type":  incident_type,
        "failed_attempts": attempts,
        "last_error":     error,
        "ts_iso":         now,
        "reversible":     True,
        "status":         "placed",
    })
    return entry


def is_repair_required(symbol: str) -> bool:
    """Cheap point-check used by the retry path before calling the broker."""
    if not symbol:
        return False
    return str(symbol) in load_state()


def get_blocked_symbols() -> set[str]:
    """Return the set of all currently quarantined symbols."""
    return set(load_state().keys())


def clear_repair(symbol: str, marker_path: str) -> bool:
    """Clear the repair flag for ``symbol``.

    REFUSES unless ``marker_path`` exists on disk. The marker file is
    created exclusively by the operator (or by a script the operator
    explicitly runs) — there is NO in-process path that creates it.
    Returns ``True`` on a successful clear, ``False`` when refused or
    when nothing was set.

    On clear an audit row ``REPAIR_REQUIRED_CLEARED`` is emitted.
    """
    if not symbol:
        return False

    if not marker_path:
        _append_audit({
            "decision_type": "REPAIR_REQUIRED_CLEAR_REFUSED",
            "actor":         "broker_repair_required",
            "symbol":        symbol,
            "reason":        "marker_path empty",
            "ts_iso":        _now_iso(),
            "reversible":    True,
            "status":        "skipped",
        })
        return False

    if not os.path.exists(marker_path):
        _append_audit({
            "decision_type": "REPAIR_REQUIRED_CLEAR_REFUSED",
            "actor":         "broker_repair_required",
            "symbol":        symbol,
            "marker_path":   marker_path,
            "reason":        "operator marker not present",
            "ts_iso":        _now_iso(),
            "reversible":    True,
            "status":        "skipped",
        })
        return False

    state = load_state()
    sym = str(symbol)
    if sym not in state:
        return False

    del state[sym]
    save_state(state)

    _append_audit({
        "decision_type":  "REPAIR_REQUIRED_CLEARED",
        "actor":          "broker_repair_required",
        "symbol":         sym,
        "marker_path":    marker_path,
        "ts_iso":         _now_iso(),
        "reversible":     True,
        "status":         "placed",
    })
    return True


__all__ = [
    "BrokerRepairRequired",
    "P13_RETRY_BUDGET",
    "P13_RETRY_BACKOFF_SECONDS",
    "SAFE_MODE_DEDUPE_WINDOW_SECONDS",
    "load_state",
    "save_state",
    "mark_repair_required",
    "is_repair_required",
    "get_blocked_symbols",
    "clear_repair",
]
