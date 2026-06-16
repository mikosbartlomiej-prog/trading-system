#!/usr/bin/env python3
"""v3.31 ETAP 3 (2026-06-16) — Propose safe-mode reconciliation actions.

CONTRACT (do not loosen)
------------------------
This script is **proposal-only**. It NEVER:

* calls the broker,
* imports ``alpaca_orders``,
* makes any network call,
* clears safe_mode (it does NOT mutate runtime_state / safe_mode_state),
* deletes ANY audit row,
* applies the proposal it writes (only WRITES the file; operator
  manually executes the actions),
* flips ``LIVE_TRADING`` / ``ALLOW_BROKER_PAPER`` / ``EDGE_GATE_ENABLED``.

PURPOSE
-------
On 2026-06-15→16 the ``incident_pattern_detector`` flipped safe_mode
46 times in 24 h (audit JSONL has 46 ``SAFE_MODE_ENTERED`` events) but
``learning-loop/runtime_state.json::safe_mode`` is still ``null`` — a
persistence / workflow-commit bug. The activation gate hard-blocks
allocator on ``SAFE_MODE_INCONSISTENT`` ahead of every other check.

This script:

1. Reads the historical safe_mode audit (last 30 days),
2. Reads ``safe_mode_state.json`` and ``runtime_state.json::safe_mode``,
3. Reads ``learning-loop/operator_markers/`` for operator confirmations
   that cover the blocked symbols,
4. Reads ``broker_repair_required_latest.json``,
5. Scans fresh P13 events,
6. Reads the equity-gap verdict,
7. Decides if reconciliation can be PROPOSED (not applied).

It produces:

* a textual, operator-readable proposal file under
  ``learning-loop/operator_markers/safe_mode_reconciliation_proposal_<date>.json``
  that lists the actions the operator must perform manually,
* a stdout summary.

Verdicts
--------
* ``RECONCILIATION_BLOCKED_OPERATOR_MARKER_REQUIRED``
    No markers cover the symbols quarantined under broker_repair.
* ``RECONCILIATION_BLOCKED_FRESH_INCIDENT``
    A fresh P13 fired *after* the most recent operator marker.
* ``RECONCILIATION_BLOCKED_EQUITY_GAP``
    Equity gap verdict is not ``EQUITY_GAP_OK``.
* ``RECONCILIATION_READY_TO_PROPOSE``
    All preconditions met; dry-run mode prints what would be written.
* ``RECONCILIATION_PROPOSAL_WRITTEN``
    Only set when ``--apply --operator-confirmed`` is supplied and
    the proposal file was atomically written.

Usage
-----
Dry-run (default)::

    python3 scripts/propose_safe_mode_reconciliation.py
    python3 scripts/propose_safe_mode_reconciliation.py --dry-run true

Apply (writes proposal — operator still executes manually)::

    python3 scripts/propose_safe_mode_reconciliation.py \\
        --apply --operator-confirmed

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

# Verdict strings
VERDICT_BLOCKED_OPERATOR_MARKER_REQUIRED = "RECONCILIATION_BLOCKED_OPERATOR_MARKER_REQUIRED"
VERDICT_BLOCKED_FRESH_INCIDENT           = "RECONCILIATION_BLOCKED_FRESH_INCIDENT"
VERDICT_BLOCKED_EQUITY_GAP               = "RECONCILIATION_BLOCKED_EQUITY_GAP"
VERDICT_READY_TO_PROPOSE                 = "RECONCILIATION_READY_TO_PROPOSE"
VERDICT_PROPOSAL_WRITTEN                 = "RECONCILIATION_PROPOSAL_WRITTEN"

# Lookback windows
SAFE_MODE_AUDIT_LOOKBACK_DAYS = 30
FRESH_P13_LOOKBACK_HOURS = 24


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


# ── Path helpers ──────────────────────────────────────────────────────────────

def _audit_dir() -> Path:
    env = os.environ.get("AUDIT_TRADING_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "journal" / "autonomy"


def _safe_mode_state_path() -> Path:
    env = os.environ.get("SAFE_MODE_STATE_PATH")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "safe_mode_state.json"


def _runtime_state_path() -> Path:
    env = os.environ.get("RUNTIME_STATE_PATH")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "runtime_state.json"


def _markers_dir() -> Path:
    env = os.environ.get("OPERATOR_MARKERS_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "operator_markers"


def _broker_repair_path() -> Path:
    env = os.environ.get("BROKER_REPAIR_REQUIRED_PATH")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "broker_repair_required_latest.json"


def _equity_gap_path() -> Path:
    env = os.environ.get("EQUITY_GAP_PATH")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "equity_gap_reconciliation_latest.json"


def _proposal_dir() -> Path:
    return _markers_dir()


def _proposal_path(date_iso: Optional[str] = None) -> Path:
    d = date_iso or _today_iso_date()
    return _proposal_dir() / f"safe_mode_reconciliation_proposal_{d}.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _today_iso_date() -> str:
    return _now().date().isoformat()


# ── Readers (all read-only, fail-soft) ────────────────────────────────────────

def _parse_iso(s: object) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _load_safe_mode_audit_events(*, lookback_days: int = SAFE_MODE_AUDIT_LOOKBACK_DAYS) -> list[dict]:
    """Read all SAFE_MODE_ENTERED / SAFE_MODE_EXITED events from JSONL."""
    out: list[dict] = []
    d = _audit_dir()
    if not d.exists():
        return out
    for delta in range(0, lookback_days + 1):
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
                    if dt.startswith("SAFE_MODE_"):
                        out.append(row)
        except OSError:
            continue
    return out


def _read_runtime_safe_mode() -> dict:
    raw = _read_json(_runtime_state_path())
    sm = raw.get("safe_mode") if isinstance(raw, dict) else None
    return sm if isinstance(sm, dict) else {}


def _read_safe_mode_state_file() -> dict:
    return _read_json(_safe_mode_state_path())


def _read_broker_repair_state() -> dict[str, dict]:
    raw = _read_json(_broker_repair_path())
    entries = raw.get("entries") if isinstance(raw, dict) else None
    if not isinstance(entries, dict):
        return {}
    return {str(k): v for k, v in entries.items() if isinstance(v, dict)}


def _read_operator_markers() -> dict[str, dict]:
    """Return mapping safe_sym -> marker payload from operator_markers dir.

    Reads everything in markers dir, filters out templates (suffix
    ``_template.md`` or ``_template.json``) and reconciliation proposals
    (which are written by THIS script).
    """
    out: dict[str, dict] = {}
    d = _markers_dir()
    if not d.exists():
        return out
    for p in sorted(d.glob("*.json")):
        name = p.name
        # Skip template files (v3.31 spec).
        if name.endswith("_template.json"):
            continue
        # Skip our own reconciliation proposals.
        if name.startswith("safe_mode_reconciliation_proposal_"):
            continue
        if name.startswith("broker_repair_clearance_proposal_"):
            continue
        try:
            with open(p, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        sym = payload.get("symbol")
        if not sym:
            continue
        # Force operator-confirmation source (template files MAY have
        # ``source != OPERATOR_MANUAL_CONFIRMATION``; filter them out).
        source = str(payload.get("source") or "")
        if source != "OPERATOR_MANUAL_CONFIRMATION":
            continue
        out[str(sym)] = payload
    return out


def _read_equity_gap_verdict() -> tuple[str, dict]:
    raw = _read_json(_equity_gap_path())
    verdict = str(raw.get("verdict") or "") if isinstance(raw, dict) else ""
    return verdict, raw


def _fresh_p13_events_since(since: datetime) -> list[dict]:
    """Read recent audit JSONL files for P13-flavoured rows since ``since``."""
    out: list[dict] = []
    d = _audit_dir()
    if not d.exists():
        return out
    # Scan up to 2 days back to span midnight.
    for delta in range(0, 3):
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
                    reason = str(row.get("reason") or "")
                    dt = str(row.get("decision_type") or "")
                    if ("P13_BRACKET_INTERLOCK" in reason
                            or "P13_bracket_interlock" in reason
                            or "P13_BRACKET_INTERLOCK" in dt):
                        ts = _parse_iso(row.get("timestamp") or row.get("ts_iso"))
                        if ts is None or ts >= since:
                            out.append(row)
        except OSError:
            continue
    return out


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class ReconciliationResult:
    verdict: str
    detail: str
    audit_enters: int
    audit_exits: int
    runtime_active: bool
    safe_mode_state_file_present: bool
    operator_markers_count: int
    blocked_symbols: list[str]
    symbols_with_marker: list[str]
    symbols_without_marker: list[str]
    fresh_p13_count: int
    equity_gap_verdict: str
    proposal_path: Optional[str] = None
    proposed_actions: list[str] = field(default_factory=list)
    schema_version: str = "v3.31"
    evaluated_at_iso: str = field(default_factory=_now_iso)
    standing_markers: list[str] = field(default_factory=lambda: _standing_markers())

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _standing_markers() -> list[str]:
    return [
        "EDGE_GATE_ENABLED=false",
        "ALLOW_BROKER_PAPER=false",
        "LIVE_TRADING_UNSUPPORTED",
        "NO_ORDER_PLACEMENT",
        "NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT",
    ]


# ── Decision logic ────────────────────────────────────────────────────────────

def _classify_marker_coverage(
    blocked_symbols: list[str],
    markers: dict[str, dict],
) -> tuple[list[str], list[str]]:
    """Split blocked symbols into (with_marker, without_marker).

    A symbol counts as "with marker" iff a marker exists under ANY of its
    aliases (e.g. ``AVAX/USD`` ↔ ``AVAX`` ↔ ``AVAXUSD``).
    """
    try:
        from symbol_normalization import aliases_for  # type: ignore
    except ImportError:
        try:
            from shared.symbol_normalization import aliases_for  # type: ignore
        except ImportError:
            def aliases_for(s):  # type: ignore
                return {str(s)}

    with_marker: list[str] = []
    without_marker: list[str] = []
    for sym in blocked_symbols:
        # Try every alias, also the canonical safe-sym used by marker file
        # naming (slash → underscore).
        alias_set = set()
        try:
            alias_set.update(aliases_for(sym) or {sym})
        except Exception:
            alias_set.add(sym)
        # Add the marker-file safe-name form as well.
        for a in list(alias_set):
            alias_set.add(str(a).replace("/", "_").replace(" ", "_"))
        if any(a in markers for a in alias_set):
            with_marker.append(sym)
        else:
            without_marker.append(sym)
    return with_marker, without_marker


def _build_proposed_actions(events: list[dict],
                            runtime: dict,
                            blocked_symbols: list[str]) -> list[str]:
    """Compose the operator-readable action list for the proposal file.

    Every action begins with "Operator:" — there is no "System:" action.
    """
    actions: list[str] = []
    # Pick the most recent SAFE_MODE_ENTERED reason/trigger as the "exit
    # justification" — operator confirms that the underlying condition is
    # cleared and emits a matching EXITED row.
    enters = [e for e in events if str(e.get("decision_type") or "") == "SAFE_MODE_ENTERED"]
    latest = enters[-1] if enters else {}
    trigger = str(latest.get("reason") or latest.get("trigger") or "P13_BRACKET_INTERLOCK")
    sym = ""
    affected = latest.get("affected_symbols")
    if isinstance(affected, list) and affected:
        sym = str(affected[0])

    sym_disp = sym or "<none>"
    actions.append(
        f"Operator: add SAFE_MODE_EXITED audit row for trigger={trigger}, "
        f"symbol={sym_disp}, exit_timestamp={_now_iso()} "
        "(append a JSON line to journal/autonomy/<today>.jsonl)."
    )
    actions.append(
        "Operator: set safe_mode_state.active=false via atomic write "
        f"(target file: {_safe_mode_state_path()}). Do NOT delete the file; "
        "rewrite it with active=false + reason describing the manual exit."
    )
    actions.append(
        "Operator: mirror runtime_state.safe_mode.active=false "
        f"(target file: {_runtime_state_path()}). Preserve every other field "
        "in runtime_state.json."
    )
    actions.append(
        "Preserve historical inconsistency evidence — do NOT delete any "
        "SAFE_MODE_ENTERED audit row. The 46 historical events stay in the "
        "journal as forensic evidence of the persistence bug."
    )
    if blocked_symbols:
        actions.append(
            "After EXITED row + state writes, broker_repair_required "
            f"entries for {sorted(blocked_symbols)} STILL remain. Clear them "
            "ONLY via scripts/propose_clear_broker_repair_canonical.py "
            "with --apply --operator-confirmed and then "
            "shared.broker_repair_required.clear_repair(symbol, marker_path)."
        )
    actions.append(
        "After all manual actions, re-run scripts/check_safe_mode_consistency.py "
        "and confirm verdict transitions to CONSISTENT."
    )
    return actions


def _evaluate(*, operator_confirmed: bool) -> tuple[ReconciliationResult, list[str]]:
    """Read inputs, classify, optionally build the proposal action list.

    Returns ``(result, proposed_actions)``. The caller may write a
    proposal file only when ``verdict == VERDICT_READY_TO_PROPOSE`` AND
    ``operator_confirmed is True``.
    """
    # 1. Audit events
    events = _load_safe_mode_audit_events()
    enters = [e for e in events if str(e.get("decision_type") or "") == "SAFE_MODE_ENTERED"]
    exits  = [e for e in events if str(e.get("decision_type") or "") == "SAFE_MODE_EXITED"]

    # 2. Runtime state + safe-mode state file
    runtime = _read_runtime_safe_mode()
    runtime_active = bool(runtime.get("active", False))
    safe_mode_state_present = _safe_mode_state_path().exists()

    # 3. Operator markers
    markers = _read_operator_markers()

    # 4. Broker repair state
    brr_entries = _read_broker_repair_state()
    blocked_symbols = sorted(brr_entries.keys())

    # 5. Equity gap
    equity_verdict, _equity_raw = _read_equity_gap_verdict()

    # 6. Fresh P13 — within last 24h
    fresh_since = _now() - timedelta(hours=FRESH_P13_LOOKBACK_HOURS)
    fresh_p13 = _fresh_p13_events_since(fresh_since)
    fresh_p13_count = len(fresh_p13)

    # 7. Classify operator-marker coverage
    with_marker, without_marker = _classify_marker_coverage(blocked_symbols, markers)

    # ── Decision rules ──
    proposed_actions: list[str] = []

    # RULE A: equity gap unresolved — block
    if equity_verdict and equity_verdict != "EQUITY_GAP_OK":
        return (ReconciliationResult(
            verdict=VERDICT_BLOCKED_EQUITY_GAP,
            detail=f"equity_gap verdict={equity_verdict} != EQUITY_GAP_OK",
            audit_enters=len(enters),
            audit_exits=len(exits),
            runtime_active=runtime_active,
            safe_mode_state_file_present=safe_mode_state_present,
            operator_markers_count=len(markers),
            blocked_symbols=blocked_symbols,
            symbols_with_marker=with_marker,
            symbols_without_marker=without_marker,
            fresh_p13_count=fresh_p13_count,
            equity_gap_verdict=equity_verdict,
        ), [])

    # RULE B: blocked symbols without operator marker — block
    # (Even if blocked_symbols is empty we still continue because the
    #  base safe_mode inconsistency is what we're trying to reconcile,
    #  not necessarily a per-symbol quarantine.)
    if without_marker:
        return (ReconciliationResult(
            verdict=VERDICT_BLOCKED_OPERATOR_MARKER_REQUIRED,
            detail=(f"{len(without_marker)} blocked symbol(s) lack an operator "
                    f"marker: {without_marker}"),
            audit_enters=len(enters),
            audit_exits=len(exits),
            runtime_active=runtime_active,
            safe_mode_state_file_present=safe_mode_state_present,
            operator_markers_count=len(markers),
            blocked_symbols=blocked_symbols,
            symbols_with_marker=with_marker,
            symbols_without_marker=without_marker,
            fresh_p13_count=fresh_p13_count,
            equity_gap_verdict=equity_verdict,
        ), [])

    # RULE C: fresh P13 since the most recent operator marker — block
    if markers and fresh_p13_count > 0:
        # Find the most recent marker timestamp.
        marker_times: list[datetime] = []
        for payload in markers.values():
            ts = _parse_iso(payload.get("timestamp_iso"))
            if ts is not None:
                marker_times.append(ts)
        most_recent_marker = max(marker_times) if marker_times else None
        if most_recent_marker is not None:
            fresh_after_marker = [
                r for r in fresh_p13
                if (_parse_iso(r.get("timestamp") or r.get("ts_iso")) or _now())
                    > most_recent_marker
            ]
            if fresh_after_marker:
                return (ReconciliationResult(
                    verdict=VERDICT_BLOCKED_FRESH_INCIDENT,
                    detail=(f"{len(fresh_after_marker)} fresh P13 event(s) after "
                            f"most recent operator marker at "
                            f"{most_recent_marker.isoformat()}"),
                    audit_enters=len(enters),
                    audit_exits=len(exits),
                    runtime_active=runtime_active,
                    safe_mode_state_file_present=safe_mode_state_present,
                    operator_markers_count=len(markers),
                    blocked_symbols=blocked_symbols,
                    symbols_with_marker=with_marker,
                    symbols_without_marker=without_marker,
                    fresh_p13_count=fresh_p13_count,
                    equity_gap_verdict=equity_verdict,
                ), [])

    # RULE D: ready
    proposed_actions = _build_proposed_actions(events, runtime, blocked_symbols)
    return (ReconciliationResult(
        verdict=VERDICT_READY_TO_PROPOSE,
        detail=("preconditions met: blocked symbols covered by markers, "
                "no fresh P13, equity gap OK"),
        audit_enters=len(enters),
        audit_exits=len(exits),
        runtime_active=runtime_active,
        safe_mode_state_file_present=safe_mode_state_present,
        operator_markers_count=len(markers),
        blocked_symbols=blocked_symbols,
        symbols_with_marker=with_marker,
        symbols_without_marker=without_marker,
        fresh_p13_count=fresh_p13_count,
        equity_gap_verdict=equity_verdict,
        proposed_actions=proposed_actions,
    ), proposed_actions)


# ── Writer ────────────────────────────────────────────────────────────────────

def _atomic_write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp, path)
    return path


def _write_proposal(result: ReconciliationResult, actions: list[str]) -> Path:
    path = _proposal_path()
    body = {
        "schema_version":     "v3.31",
        "type":               "safe_mode_reconciliation_proposal",
        "verdict":            result.verdict,
        "evaluated_at_iso":   result.evaluated_at_iso,
        "blocked_symbols":    result.blocked_symbols,
        "symbols_with_marker": result.symbols_with_marker,
        "symbols_without_marker": result.symbols_without_marker,
        "audit_enters":       result.audit_enters,
        "audit_exits":        result.audit_exits,
        "runtime_active":     result.runtime_active,
        "safe_mode_state_file_present": result.safe_mode_state_file_present,
        "fresh_p13_count":    result.fresh_p13_count,
        "equity_gap_verdict": result.equity_gap_verdict,
        "operator_markers_count": result.operator_markers_count,
        "proposed_actions":   actions,
        "note":               (
            "This file is a PROPOSAL only. It does NOT execute any action. "
            "The operator must perform each action manually."
        ),
        "standing_markers":   _standing_markers(),
    }
    return _atomic_write_json(path, body)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _str_to_bool(s: str) -> bool:
    return str(s).strip().lower() in {"1", "true", "yes", "on"}


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="propose_safe_mode_reconciliation.py",
        description=(
            "Propose (do not execute) actions to reconcile the safe-mode "
            "persistence inconsistency. Default is DRY-RUN. Pass --apply "
            "--operator-confirmed to WRITE the proposal file (operator still "
            "executes manually)."
        ),
    )
    p.add_argument("--dry-run", default="true",
                   help="When 'true' (default) print summary without writing.")
    p.add_argument("--apply", action="store_true",
                   help="Write the proposal file (operator-confirmed required).")
    p.add_argument("--operator-confirmed", action="store_true",
                   help="REQUIRED to write the proposal. Without it, refuses.")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)

    dry_run_flag = _str_to_bool(args.dry_run)
    # Apply path: requires BOTH --apply AND --operator-confirmed AND not
    # --dry-run=true. Otherwise we're in dry-run mode.
    apply_mode = bool(args.apply) and bool(args.operator_confirmed) and not dry_run_flag

    result, actions = _evaluate(operator_confirmed=apply_mode)

    proposal_written: Optional[Path] = None
    if apply_mode and result.verdict == VERDICT_READY_TO_PROPOSE:
        proposal_written = _write_proposal(result, actions)
        result.verdict = VERDICT_PROPOSAL_WRITTEN
        result.detail = (result.detail + f" — proposal written to "
                         f"{proposal_written}")
        result.proposal_path = str(proposal_written)

    # Refusal: --apply WITHOUT --operator-confirmed prints refusal.
    if bool(args.apply) and not bool(args.operator_confirmed):
        print("REFUSED: --apply requires --operator-confirmed. Run with both flags "
              "to write the proposal file. The proposal NEVER auto-executes.")

    print(f"propose_safe_mode_reconciliation: verdict={result.verdict}")
    print(f"  detail={result.detail}")
    print(f"  audit_enters={result.audit_enters}  audit_exits={result.audit_exits}")
    print(f"  runtime_active={result.runtime_active}  "
          f"safe_mode_state_file_present={result.safe_mode_state_file_present}")
    print(f"  blocked_symbols={result.blocked_symbols}")
    print(f"  symbols_with_marker={result.symbols_with_marker}")
    print(f"  symbols_without_marker={result.symbols_without_marker}")
    print(f"  fresh_p13_count={result.fresh_p13_count}")
    print(f"  equity_gap_verdict={result.equity_gap_verdict}")
    if proposal_written:
        print(f"  PROPOSAL WRITTEN: {proposal_written}")
    elif result.verdict == VERDICT_READY_TO_PROPOSE:
        print("  (dry-run — pass --apply --operator-confirmed to write proposal)")
    for m in _standing_markers():
        print(f"  marker: {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "VERDICT_BLOCKED_OPERATOR_MARKER_REQUIRED",
    "VERDICT_BLOCKED_FRESH_INCIDENT",
    "VERDICT_BLOCKED_EQUITY_GAP",
    "VERDICT_READY_TO_PROPOSE",
    "VERDICT_PROPOSAL_WRITTEN",
    "ReconciliationResult",
    "main",
    # Invariants (consumed by tests)
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT",
    "EDGE_GATE_ENABLED",
    "ALLOW_BROKER_PAPER",
]
