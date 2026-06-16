"""v3.28 ETAP 4 (2026-06-16) — Retry-storm precondition + counter helper.

CONTAINMENT MODULE — read this before changing anything.

PROBLEM (2026-06-15 AVAXUSD case)
---------------------------------
exit-monitor / safe_close fired ~67 identical broker close attempts
for AVAXUSD in ~5.5h. Every attempt returned HTTP 403. There was no
in-process retry counter, no backoff, no quarantine. Each cron tick
called safe_close fresh.

WHAT THIS MODULE DOES
---------------------
* ``should_skip_broker_call(symbol)`` — answers the question
  "is this symbol currently quarantined?" without making any network
  call. Wraps ``broker_repair_required.is_repair_required``.

* ``record_broker_close_failure(symbol, error, incident_type)`` —
  bumps an in-memory + on-disk counter of consecutive failures for
  ``symbol``. On the 3rd consecutive failure (``P13_RETRY_BUDGET``)
  it calls ``broker_repair_required.mark_repair_required`` which
  freezes future calls for that symbol until an operator clears it.

* ``record_broker_close_success(symbol)`` — resets the counter on a
  successful close (so the next unrelated failure starts at attempt
  1 again).

* ``backoff_seconds_for_attempt(n)`` — returns the configured
  backoff between attempts (60s, 300s, 1800s). The caller (cron) is
  responsible for actually sleeping / deferring; this is a pure
  read.

HARD INVARIANTS
---------------
* NEVER imports ``alpaca_orders``.
* NEVER calls ``submit_order`` / ``place_order`` / ``safe_close`` /
  ``cancel_order``.
* NEVER makes network calls.
* NEVER auto-clears safe_mode.
* The 3-failure budget is per-symbol per-session (counter file lives
  on disk so it survives cron restarts).

WIRING CONTRACT
---------------
``exit-monitor/monitor.py`` (and any other caller of
``alpaca_orders.safe_close``) must:

1. Before calling safe_close::

       if retry_storm_containment.should_skip_broker_call(sym):
           emit_audit(REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE, symbol=sym)
           continue   # do NOT call broker

2. After a failed safe_close::

       retry_storm_containment.record_broker_close_failure(
           sym, error=..., incident_type="P13_BRACKET_INTERLOCK")

3. After a successful safe_close::

       retry_storm_containment.record_broker_close_success(sym)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from broker_repair_required import (  # type: ignore
        P13_RETRY_BUDGET,
        P13_RETRY_BACKOFF_SECONDS,
        SAFE_MODE_DEDUPE_WINDOW_SECONDS,
        is_repair_required,
        mark_repair_required,
    )
except ImportError:
    from shared.broker_repair_required import (  # type: ignore
        P13_RETRY_BUDGET,
        P13_RETRY_BACKOFF_SECONDS,
        SAFE_MODE_DEDUPE_WINDOW_SECONDS,
        is_repair_required,
        mark_repair_required,
    )


_REPO_ROOT = Path(__file__).resolve().parent.parent


def _counters_path() -> Path:
    env = os.environ.get("RETRY_STORM_COUNTERS_PATH")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "retry_storm_counters_latest.json"


def _audit_dir() -> Path:
    env = os.environ.get("AUDIT_TRADING_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "journal" / "autonomy"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _load_counters() -> dict[str, int]:
    p = _counters_path()
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            return {str(k): int(v) for k, v in raw.items() if isinstance(v, (int, float))}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return {}


def _save_counters(counters: dict[str, int]) -> None:
    p = _counters_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(counters, fh, indent=2, sort_keys=True)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        os.replace(tmp, p)
    except OSError:
        # Fail-soft — losing the counter only loses backoff, not safety.
        return


def _append_audit(event: dict) -> None:
    try:
        d = _audit_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{_today_iso_date()}.jsonl"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True, default=str) + "\n")
    except OSError:
        return


# ── Public API ────────────────────────────────────────────────────────────────

def should_skip_broker_call(symbol: str) -> bool:
    """True iff ``symbol`` is currently quarantined.

    Callers must check this BEFORE invoking any broker close path.
    On True, callers must NOT call safe_close / submit_order / etc.
    """
    if not symbol:
        return False
    return is_repair_required(symbol)


def record_broker_close_failure(
    symbol: str,
    *,
    error: str = "",
    incident_type: str = "P13_BRACKET_INTERLOCK",
) -> int:
    """Bump the consecutive-failures counter for ``symbol``.

    Returns the new attempt count. When the count reaches
    ``P13_RETRY_BUDGET`` (3), the symbol is quarantined via
    ``broker_repair_required.mark_repair_required`` and future calls
    to ``should_skip_broker_call`` return True until the operator
    clears the marker.

    An audit row of type ``BROKER_CLOSE_FAILURE_RECORDED`` is
    appended per call (so storms remain visible in the JSONL even
    while suppressed).
    """
    if not symbol:
        return 0
    sym = str(symbol)
    counters = _load_counters()
    new_count = int(counters.get(sym, 0)) + 1
    counters[sym] = new_count
    _save_counters(counters)

    _append_audit({
        "decision_type":  "BROKER_CLOSE_FAILURE_RECORDED",
        "actor":          "retry_storm_containment",
        "symbol":         sym,
        "attempt":        new_count,
        "budget":         P13_RETRY_BUDGET,
        "error":          error,
        "incident_type":  incident_type,
        "ts_iso":         _now_iso(),
        "reversible":     True,
        "status":         "placed",
    })

    if new_count >= P13_RETRY_BUDGET:
        # Quarantine the symbol. mark_repair_required is idempotent so
        # repeated calls just bump its own failed_attempts counter.
        try:
            mark_repair_required(
                sym,
                incident_type=incident_type,
                error=error,
                manual_action_required=(
                    "Operator must (1) cancel any open Alpaca orders for this "
                    "symbol, (2) verify the broker-side position state matches "
                    "the audit JSONL, then (3) create an operator marker file "
                    "and call broker_repair_required.clear_repair()."
                ),
                allowed_next_actions=("operator_marker_required",),
                safe_mode_reason=(
                    f"retry-storm: {incident_type} on {sym} hit P13 budget "
                    f"({P13_RETRY_BUDGET} consecutive failures)"
                ),
            )
        except Exception as exc:
            # Fail-soft: even if the persistence path fails, we still
            # tell the caller "you've hit the budget" so it stops
            # retrying for the rest of this session.
            _append_audit({
                "decision_type": "REPAIR_REQUIRED_MARK_FAILED",
                "actor":         "retry_storm_containment",
                "symbol":        sym,
                "error":         f"{type(exc).__name__}: {exc}",
                "ts_iso":        _now_iso(),
                "reversible":    True,
                "status":        "failed",
            })

    return new_count


def record_broker_close_success(symbol: str) -> None:
    """Reset the consecutive-failures counter for ``symbol``.

    Called after a successful broker close so the next unrelated
    failure starts the budget over from attempt 1. Does NOT clear
    the broker_repair_required state — that requires the operator.
    """
    if not symbol:
        return
    sym = str(symbol)
    counters = _load_counters()
    if sym in counters:
        del counters[sym]
        _save_counters(counters)


def emit_skip_audit(symbol: str, *, incident_type: str = "") -> None:
    """Convenience emitter — record that we just skipped a broker call.

    Callers use this from within the precondition path so the JSONL
    shows when the skip happened. Separate from ``mark_repair_required``
    audit rows so the two events stay distinguishable.
    """
    if not symbol:
        return
    _append_audit({
        "decision_type":  "REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE",
        "actor":          "retry_storm_containment",
        "symbol":         str(symbol),
        "incident_type":  incident_type,
        "ts_iso":         _now_iso(),
        "reversible":     True,
        "status":         "skipped",
    })


def backoff_seconds_for_attempt(attempt: int) -> int:
    """Return the configured backoff for the given attempt index (1-based).

    Attempt 1 → backoff before retry 2 → 60s.
    Attempt 2 → backoff before retry 3 → 300s.
    Attempt 3 → after this the symbol is quarantined → 1800s.
    Any attempt ≥ ``len(P13_RETRY_BACKOFF_SECONDS)`` returns the last
    (largest) value.
    """
    if attempt < 1:
        return 0
    idx = min(attempt - 1, len(P13_RETRY_BACKOFF_SECONDS) - 1)
    return int(P13_RETRY_BACKOFF_SECONDS[idx])


__all__ = [
    "should_skip_broker_call",
    "record_broker_close_failure",
    "record_broker_close_success",
    "emit_skip_audit",
    "backoff_seconds_for_attempt",
    "P13_RETRY_BUDGET",
    "P13_RETRY_BACKOFF_SECONDS",
    "SAFE_MODE_DEDUPE_WINDOW_SECONDS",
]
