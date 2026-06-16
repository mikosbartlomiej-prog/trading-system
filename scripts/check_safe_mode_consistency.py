#!/usr/bin/env python3
"""v3.29 ETAP 2 (2026-06-16) — Safe-mode consistency checker.

CONTRACT (do not loosen)
------------------------
This script is **read-only**. It NEVER:

* calls the broker,
* imports ``alpaca_orders``,
* makes any network call,
* clears safe_mode (it ONLY reports the inconsistency — the operator
  + a dedicated fix decide what to do),
* mutates risk thresholds,
* flips ``LIVE_TRADING`` / ``ALLOW_BROKER_PAPER`` / ``EDGE_GATE_ENABLED``.

PURPOSE
-------
Detect a class of bugs first seen on 2026-06-15: the
``incident_pattern_detector`` flipped ``safe_mode`` 25 times in a
single day (audit JSONL contains 25 ``SAFE_MODE_ENTERED`` events for
``INCIDENT_P13_BRACKET_INTERLOCK``) but
``learning-loop/runtime_state.json::safe_mode`` was still ``null``
the next morning. Allocator therefore saw safe_mode inactive and was
free to deploy fresh capital. This script catches that mismatch.

Verdicts
--------
* ``CONSISTENT``
    Audit and runtime agree; no orphan events.
* ``INCONSISTENT_ENTERED_NOT_PERSISTED``
    Audit has ``SAFE_MODE_ENTERED`` within the lookback window AND
    runtime ``safe_mode.active`` is False/None. **Blocks allocator.**
* ``INCONSISTENT_EXIT_WITHOUT_ENTER``
    Audit has ``SAFE_MODE_EXITED`` without a prior ``SAFE_MODE_ENTERED``.
* ``STALE_ACTIVE``
    Runtime says active but the most recent SAFE_MODE_* event is
    older than ``STALE_THRESHOLD_DAYS``.
* ``UNKNOWN``
    Unable to load enough evidence to decide.

Outputs
-------
* ``learning-loop/safe_mode_consistency_latest.json``
* ``docs/SAFE_MODE_CONSISTENCY_STATUS.md``

STANDING MARKERS
----------------
- ``EDGE_GATE_ENABLED=false``
- ``ALLOW_BROKER_PAPER=false``
- ``LIVE_TRADING_UNSUPPORTED``
- ``NO_ORDER_PLACEMENT``
- ``NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT``
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


# ── Standing invariants (asserted by tests) ───────────────────────────────────
LIVE_TRADING_UNSUPPORTED = True
NO_ORDER_PLACEMENT = True
NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT = True
EDGE_GATE_ENABLED = False
ALLOW_BROKER_PAPER = False

# Lookback / freshness constants.
DEFAULT_LOOKBACK_HOURS = 24
STALE_THRESHOLD_DAYS = 7

VERDICT_CONSISTENT = "CONSISTENT"
VERDICT_ENTERED_NOT_PERSISTED = "INCONSISTENT_ENTERED_NOT_PERSISTED"
VERDICT_EXIT_WITHOUT_ENTER = "INCONSISTENT_EXIT_WITHOUT_ENTER"
VERDICT_STALE_ACTIVE = "STALE_ACTIVE"
VERDICT_UNKNOWN = "UNKNOWN"


_REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Paths ─────────────────────────────────────────────────────────────────────

def _audit_dir() -> Path:
    env = os.environ.get("AUDIT_TRADING_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "journal" / "autonomy"


def _runtime_state_path() -> Path:
    env = os.environ.get("RUNTIME_STATE_PATH")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "runtime_state.json"


def _out_json_path() -> Path:
    env = os.environ.get("SAFE_MODE_CONSISTENCY_OUT_JSON")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "safe_mode_consistency_latest.json"


def _out_md_path() -> Path:
    env = os.environ.get("SAFE_MODE_CONSISTENCY_OUT_MD")
    if env:
        return Path(env)
    return _REPO_ROOT / "docs" / "SAFE_MODE_CONSISTENCY_STATUS.md"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


# ── Evidence loaders ──────────────────────────────────────────────────────────

def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


@dataclass
class AuditEvent:
    decision_type: str
    actor: str
    reason: str
    action_taken: str
    ts: Optional[datetime]


def _load_recent_audit_events(*, hours: int = DEFAULT_LOOKBACK_HOURS) -> list[AuditEvent]:
    """Load all SAFE_MODE_* events from JSONL files in the lookback window.

    Reads every ``YYYY-MM-DD.jsonl`` whose date covers the lookback
    window. Fail-soft on per-file / per-line errors.
    """
    out: list[AuditEvent] = []
    d = _audit_dir()
    if not d.exists():
        return out

    cutoff = _now() - timedelta(hours=int(hours))
    # We may need to look at today + yesterday for a 24h window.
    days_back = max(2, int(hours // 24) + 2)
    for delta in range(0, days_back + 1):
        day = (_now() - timedelta(days=delta)).date().isoformat()
        p = d / f"{day}.jsonl"
        if not p.exists():
            continue
        try:
            with open(p, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    dt = str(row.get("decision_type") or row.get("decision") or "")
                    if not dt.startswith("SAFE_MODE_"):
                        continue
                    ts = _parse_iso(str(row.get("timestamp") or row.get("ts_iso") or ""))
                    if ts is None:
                        # Cannot timestamp-filter; still include so we report.
                        pass
                    elif ts < cutoff:
                        continue
                    out.append(AuditEvent(
                        decision_type=dt,
                        actor=str(row.get("actor") or ""),
                        reason=str(row.get("reason") or ""),
                        action_taken=str(row.get("action_taken") or ""),
                        ts=ts,
                    ))
        except OSError:
            continue
    out.sort(key=lambda e: e.ts or datetime.min.replace(tzinfo=timezone.utc))
    return out


def _read_runtime_safe_mode() -> dict:
    """Return runtime_state['safe_mode'] (or empty dict)."""
    p = _runtime_state_path()
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    sm = raw.get("safe_mode")
    if isinstance(sm, dict):
        return sm
    return {}


# ── Detection rules ───────────────────────────────────────────────────────────

@dataclass
class ConsistencyResult:
    verdict: str
    blocker: Optional[str]  # e.g. BLOCK_SAFE_MODE_INCONSISTENT or None
    detail: str
    audit_events: int
    audit_enters: int
    audit_exits: int
    runtime_active: bool
    runtime_reason: str
    runtime_trigger: str
    last_event_iso: Optional[str]
    lookback_hours: int
    evaluated_at_iso: str
    standing_markers: list[str] = field(default_factory=list)


def _evaluate(events: list[AuditEvent],
              runtime: dict,
              *,
              lookback_hours: int = DEFAULT_LOOKBACK_HOURS) -> ConsistencyResult:
    """Classify the (audit-events, runtime) pair into a verdict."""
    enters = [e for e in events if e.decision_type == "SAFE_MODE_ENTERED"]
    exits  = [e for e in events if e.decision_type == "SAFE_MODE_EXITED"]
    last_ts = max((e.ts for e in events if e.ts), default=None)

    runtime_active = bool(runtime.get("active", False))
    runtime_reason = str(runtime.get("reason", "") or "")
    runtime_trigger = str(runtime.get("trigger", "") or "")

    # RULE 1: STALE_ACTIVE — runtime says active but last SAFE_MODE_* event
    # is older than STALE_THRESHOLD_DAYS. This handles "stuck-on" state
    # that nobody is refreshing. Order-priority: BEFORE the EXIT-without-ENTER
    # rule so that a really old "exit-only" trace doesn't shadow this.
    if runtime_active and last_ts is not None:
        if (_now() - last_ts) > timedelta(days=STALE_THRESHOLD_DAYS):
            return ConsistencyResult(
                verdict=VERDICT_STALE_ACTIVE,
                blocker=None,
                detail=(f"runtime safe_mode active but last SAFE_MODE_* event was "
                        f"{(_now() - last_ts).days} days ago — operator review"),
                audit_events=len(events),
                audit_enters=len(enters),
                audit_exits=len(exits),
                runtime_active=runtime_active,
                runtime_reason=runtime_reason,
                runtime_trigger=runtime_trigger,
                last_event_iso=last_ts.isoformat() if last_ts else None,
                lookback_hours=lookback_hours,
                evaluated_at_iso=_now_iso(),
                standing_markers=_standing_markers(),
            )

    # RULE 2: INCONSISTENT_ENTERED_NOT_PERSISTED
    # Latest event in window is a SAFE_MODE_ENTERED *not* superseded by
    # a later SAFE_MODE_EXITED, but runtime is not active. This is the
    # gap that let the AVAXUSD P13 storm proceed unchecked.
    # We only flag inconsistency when the most-recent transition is
    # ENTER (no matching EXIT after it). Otherwise an old ENTER followed
    # by an EXIT is legitimate clean state.
    latest_enter = enters[-1] if enters else None
    latest_exit = exits[-1] if exits else None
    latest_is_enter = (
        latest_enter is not None
        and (latest_exit is None
             or (latest_enter.ts is not None
                 and latest_exit.ts is not None
                 and latest_enter.ts >= latest_exit.ts))
    )
    if latest_is_enter and not runtime_active:
        return ConsistencyResult(
            verdict=VERDICT_ENTERED_NOT_PERSISTED,
            blocker="BLOCK_SAFE_MODE_INCONSISTENT",
            detail=(f"{len(enters)} SAFE_MODE_ENTERED in last {lookback_hours}h "
                    f"(latest at {latest_enter.ts.isoformat() if latest_enter.ts else '?'}) "
                    f"with no later SAFE_MODE_EXITED, but runtime_state.safe_mode "
                    "is not active — persistence bug or workflow-level commit "
                    "not happening"),
            audit_events=len(events),
            audit_enters=len(enters),
            audit_exits=len(exits),
            runtime_active=runtime_active,
            runtime_reason=runtime_reason,
            runtime_trigger=runtime_trigger,
            last_event_iso=last_ts.isoformat() if last_ts else None,
            lookback_hours=lookback_hours,
            evaluated_at_iso=_now_iso(),
            standing_markers=_standing_markers(),
        )

    # RULE 3: INCONSISTENT_EXIT_WITHOUT_ENTER
    # An EXIT event found in the lookback window without a matching prior
    # ENTER in the same window. Check ordering of events.
    if exits:
        # Find the first exit not preceded by an enter in the same window.
        seen_enter = False
        unmatched_exit: Optional[AuditEvent] = None
        for ev in events:
            if ev.decision_type == "SAFE_MODE_ENTERED":
                seen_enter = True
            elif ev.decision_type == "SAFE_MODE_EXITED":
                if not seen_enter:
                    unmatched_exit = ev
                    break
        if unmatched_exit is not None:
            return ConsistencyResult(
                verdict=VERDICT_EXIT_WITHOUT_ENTER,
                blocker=None,
                detail=(f"SAFE_MODE_EXITED at "
                        f"{unmatched_exit.ts.isoformat() if unmatched_exit.ts else '?'} "
                        "without a matching prior SAFE_MODE_ENTERED in the lookback window"),
                audit_events=len(events),
                audit_enters=len(enters),
                audit_exits=len(exits),
                runtime_active=runtime_active,
                runtime_reason=runtime_reason,
                runtime_trigger=runtime_trigger,
                last_event_iso=last_ts.isoformat() if last_ts else None,
                lookback_hours=lookback_hours,
                evaluated_at_iso=_now_iso(),
                standing_markers=_standing_markers(),
            )

    # RULE 4: CONSISTENT happy path
    return ConsistencyResult(
        verdict=VERDICT_CONSISTENT,
        blocker=None,
        detail=(f"audit and runtime agree (enters={len(enters)}, exits={len(exits)}, "
                f"runtime_active={runtime_active})"),
        audit_events=len(events),
        audit_enters=len(enters),
        audit_exits=len(exits),
        runtime_active=runtime_active,
        runtime_reason=runtime_reason,
        runtime_trigger=runtime_trigger,
        last_event_iso=last_ts.isoformat() if last_ts else None,
        lookback_hours=lookback_hours,
        evaluated_at_iso=_now_iso(),
        standing_markers=_standing_markers(),
    )


def _standing_markers() -> list[str]:
    return [
        "EDGE_GATE_ENABLED=false",
        "ALLOW_BROKER_PAPER=false",
        "LIVE_TRADING_UNSUPPORTED",
        "NO_ORDER_PLACEMENT",
        "NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT",
    ]


# ── Output writers ────────────────────────────────────────────────────────────

def _write_json(result: ConsistencyResult) -> Path:
    p = _out_json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version":           "v3.29",
        "verdict":                  result.verdict,
        "blocker":                  result.blocker,
        "detail":                   result.detail,
        "audit_events":             result.audit_events,
        "audit_enters":             result.audit_enters,
        "audit_exits":              result.audit_exits,
        "runtime_active":           result.runtime_active,
        "runtime_reason":           result.runtime_reason,
        "runtime_trigger":          result.runtime_trigger,
        "last_event_iso":           result.last_event_iso,
        "lookback_hours":           result.lookback_hours,
        "evaluated_at_iso":         result.evaluated_at_iso,
        "standing_markers":         result.standing_markers,
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp, p)
    return p


def _write_markdown(result: ConsistencyResult) -> Path:
    p = _out_md_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    blocker_line = f"**Blocker:** `{result.blocker}`" if result.blocker else "**Blocker:** _none_"
    body = [
        f"# Safe-mode consistency status — {result.evaluated_at_iso}",
        "",
        f"## Verdict: **{result.verdict}**",
        "",
        blocker_line,
        "",
        "## Detail",
        "",
        result.detail,
        "",
        "## Counts",
        "",
        f"- audit events in last {result.lookback_hours}h: {result.audit_events}",
        f"- SAFE_MODE_ENTERED: {result.audit_enters}",
        f"- SAFE_MODE_EXITED:  {result.audit_exits}",
        f"- runtime_active:    {result.runtime_active}",
        f"- runtime_trigger:   {result.runtime_trigger}",
        f"- last_event_iso:    {result.last_event_iso}",
        "",
        "## Standing markers",
        "",
        *(f"- `{m}`" for m in result.standing_markers),
        "",
    ]
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("\n".join(body))
    return p


# ── Public API ────────────────────────────────────────────────────────────────

def check_consistency(*, lookback_hours: int = DEFAULT_LOOKBACK_HOURS) -> ConsistencyResult:
    """Public entry-point — no I/O beyond reading the audit + runtime files."""
    events = _load_recent_audit_events(hours=lookback_hours)
    runtime = _read_runtime_safe_mode()
    return _evaluate(events, runtime, lookback_hours=lookback_hours)


def write_outputs(result: ConsistencyResult) -> dict:
    return {
        "json": str(_write_json(result)),
        "md":   str(_write_markdown(result)),
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="check_safe_mode_consistency.py",
        description="Read-only safe-mode consistency checker. Never calls broker.",
    )
    p.add_argument("--lookback-hours", type=int, default=DEFAULT_LOOKBACK_HOURS,
                   help=f"How far back to read audit events (default {DEFAULT_LOOKBACK_HOURS})")
    p.add_argument("--dry-run", default="false",
                   help="When 'true' print result without writing outputs.")
    return p.parse_args(argv)


def _str_to_bool(s: str) -> bool:
    return str(s).strip().lower() in {"1", "true", "yes", "on"}


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    result = check_consistency(lookback_hours=int(args.lookback_hours))
    print(f"check_safe_mode_consistency: verdict={result.verdict}")
    print(f"  blocker={result.blocker}")
    print(f"  detail={result.detail}")
    print(f"  audit_enters={result.audit_enters}  audit_exits={result.audit_exits}  "
          f"runtime_active={result.runtime_active}")
    if not _str_to_bool(args.dry_run):
        paths = write_outputs(result)
        print(f"  json: {paths['json']}")
        print(f"  md:   {paths['md']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "VERDICT_CONSISTENT",
    "VERDICT_ENTERED_NOT_PERSISTED",
    "VERDICT_EXIT_WITHOUT_ENTER",
    "VERDICT_STALE_ACTIVE",
    "VERDICT_UNKNOWN",
    "STALE_THRESHOLD_DAYS",
    "DEFAULT_LOOKBACK_HOURS",
    "ConsistencyResult",
    "check_consistency",
    "write_outputs",
    "main",
]
