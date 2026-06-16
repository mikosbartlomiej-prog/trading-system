#!/usr/bin/env python3
"""v3.31 ETAP 4 (2026-06-16) — Propose broker-repair canonical clearance.

CONTRACT (do not loosen)
------------------------
This script is **proposal-only**. It NEVER:

* calls the broker,
* imports ``alpaca_orders``,
* clears ``broker_repair_required`` (only WRITES a proposal listing
  the per-symbol clear_repair calls the operator must manually run),
* mutates ``safe_mode``,
* makes any network call,
* flips ``LIVE_TRADING`` / ``ALLOW_BROKER_PAPER`` / ``EDGE_GATE_ENABLED``.

PURPOSE
-------
After v3.30 canonical-key normalization the canonical broker-repair
state has three entries: ``AVAX/USD``, ``ETH/USD``, ``LTC/USD``. To
clear any of them, the operator must:

1. Visit the Alpaca paper dashboard, manually close stuck OCO legs /
   dust positions for that symbol,
2. Run ``record_operator_repair_confirmation.py --operator-confirmed``
   with all the per-symbol fields,
3. Verify no fresh broker failure happened since the marker.

This script automates the *validation* of all those preconditions —
it does NOT do step (1)/(2) and it does NOT clear the entry. It only
WRITES a textual proposal listing the safe ``clear_repair`` calls for
the operator to run manually.

Per-symbol verdict
------------------
* ``CLEARANCE_BLOCKED_NO_MARKER``
    No operator-confirmation marker for this symbol's alias set.
* ``CLEARANCE_BLOCKED_MARKER_BEFORE_LAST_FAILURE``
    Operator marker timestamp predates the last Alpaca 4xx for this
    symbol in the audit journal.
* ``CLEARANCE_BLOCKED_FRESH_FAILURE``
    Alpaca 4xx for this symbol observed after the marker.
* ``CLEARANCE_BLOCKED_SAFE_MODE``
    Safe-mode consistency check is still inconsistent or safe_mode is
    still active.
* ``CLEARANCE_BLOCKED_EQUITY_GAP``
    Equity gap verdict is not ``EQUITY_GAP_OK``.
* ``CLEARANCE_READY``
    Symbol is ready for the clearance proposal to be written.
* ``CLEARANCE_PROPOSAL_WRITTEN``
    Only set when ``--apply --operator-confirmed`` is supplied AND
    every blocked symbol is ``CLEARANCE_READY``.

Usage
-----
Dry-run (default)::

    python3 scripts/propose_clear_broker_repair_canonical.py
    python3 scripts/propose_clear_broker_repair_canonical.py --dry-run true

Apply (writes proposal — operator still executes manually)::

    python3 scripts/propose_clear_broker_repair_canonical.py \\
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


# Per-symbol verdicts
V_NO_MARKER             = "CLEARANCE_BLOCKED_NO_MARKER"
V_MARKER_BEFORE_FAILURE = "CLEARANCE_BLOCKED_MARKER_BEFORE_LAST_FAILURE"
V_FRESH_FAILURE         = "CLEARANCE_BLOCKED_FRESH_FAILURE"
V_SAFE_MODE             = "CLEARANCE_BLOCKED_SAFE_MODE"
V_EQUITY_GAP            = "CLEARANCE_BLOCKED_EQUITY_GAP"
V_READY                 = "CLEARANCE_READY"
V_PROPOSAL_WRITTEN      = "CLEARANCE_PROPOSAL_WRITTEN"

# Retry-storm window for "no recent broker call activity" check
RETRY_STORM_WINDOW_MINUTES = 60
FRESH_FAILURE_LOOKBACK_HOURS = 48


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


# ── Path helpers ──────────────────────────────────────────────────────────────

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


def _safe_mode_consistency_path() -> Path:
    env = os.environ.get("SAFE_MODE_CONSISTENCY_PATH")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "safe_mode_consistency_latest.json"


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


def _proposal_path(date_iso: Optional[str] = None) -> Path:
    d = date_iso or _today_iso_date()
    return _markers_dir() / f"broker_repair_clearance_proposal_{d}.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _today_iso_date() -> str:
    return _now().date().isoformat()


# ── Readers ───────────────────────────────────────────────────────────────────

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


def _read_broker_repair_state() -> dict[str, dict]:
    raw = _read_json(_broker_repair_path())
    entries = raw.get("entries") if isinstance(raw, dict) else None
    if not isinstance(entries, dict):
        return {}
    return {str(k): v for k, v in entries.items() if isinstance(v, dict)}


def _read_operator_markers() -> dict[str, dict]:
    """Map of safe-sym → marker payload (filters templates + proposals)."""
    out: dict[str, dict] = {}
    d = _markers_dir()
    if not d.exists():
        return out
    for p in sorted(d.glob("*.json")):
        name = p.name
        if name.endswith("_template.json"):
            continue
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
        source = str(payload.get("source") or "")
        if not sym or source != "OPERATOR_MANUAL_CONFIRMATION":
            continue
        # Index by the alias used in the marker payload as well as the
        # safe filename form for robust lookup.
        out[str(sym)] = payload
        out[str(sym).replace("/", "_").replace(" ", "_")] = payload
    return out


def _read_safe_mode_consistency_verdict() -> tuple[str, dict]:
    raw = _read_json(_safe_mode_consistency_path())
    verdict = str(raw.get("verdict") or "") if isinstance(raw, dict) else ""
    return verdict, raw


def _read_runtime_safe_mode_active() -> bool:
    raw = _read_json(_runtime_state_path())
    sm = raw.get("safe_mode") if isinstance(raw, dict) else None
    if not isinstance(sm, dict):
        return False
    return bool(sm.get("active", False))


def _read_equity_gap_verdict() -> str:
    raw = _read_json(_equity_gap_path())
    return str(raw.get("verdict") or "") if isinstance(raw, dict) else ""


def _scan_audit_for_symbol_failures(symbol: str,
                                    aliases: set[str],
                                    lookback_hours: int,
                                    *,
                                    now: Optional[datetime] = None) -> list[tuple[datetime, dict]]:
    """Return list of (timestamp, row) for Alpaca 4xx errors on this symbol."""
    out: list[tuple[datetime, dict]] = []
    d = _audit_dir()
    if not d.exists():
        return out
    cutoff = (now or _now()) - timedelta(hours=lookback_hours)
    # Scan today + previous N days to cover lookback window.
    days_back = max(2, lookback_hours // 24 + 2)
    for delta in range(0, days_back + 1):
        day = ((now or _now()) - timedelta(days=delta)).date().isoformat()
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
                    # Symbol match — affected_symbols list or single-string
                    affected = row.get("affected_symbols") or []
                    if isinstance(affected, str):
                        affected = [affected]
                    affected_list = [str(s) for s in affected]
                    sym_field = str(row.get("symbol") or "")
                    if sym_field:
                        affected_list.append(sym_field)
                    if not any(a in aliases for a in affected_list):
                        continue
                    # Failure signal — Alpaca 403 / 422, or REPAIR_REQUIRED
                    # mark, or CLOSE_POSITION FAILED, etc.
                    reason  = str(row.get("reason") or "")
                    errors  = row.get("errors") or []
                    err_str = ""
                    if isinstance(errors, list):
                        err_str = " | ".join(str(e) for e in errors)
                    status  = str(row.get("status") or "")
                    decision = str(row.get("decision") or "")
                    dtype   = str(row.get("decision_type") or "")
                    failure_signals = (
                        "Alpaca 403", "Alpaca 422", "403", "422",
                        "insufficient balance", "insufficient_balance",
                        "qty must be > 0",
                    )
                    has_failure = (
                        any(s in reason for s in failure_signals)
                        or any(s in err_str for s in failure_signals)
                        or status == "failed"
                        or decision == "FAILED"
                        or dtype in {"CLOSE_POSITION", "EMERGENCY_CLOSE"}
                            and (decision == "FAILED" or status == "failed")
                        or dtype.startswith("REPAIR_REQUIRED_")
                    )
                    if not has_failure:
                        continue
                    ts = _parse_iso(row.get("timestamp") or row.get("ts_iso"))
                    if ts is None:
                        continue
                    if ts < cutoff:
                        continue
                    out.append((ts, row))
        except OSError:
            continue
    out.sort(key=lambda kv: kv[0])
    return out


def _aliases_for_symbol(symbol: str) -> set[str]:
    try:
        from symbol_normalization import aliases_for  # type: ignore
    except ImportError:
        try:
            from shared.symbol_normalization import aliases_for  # type: ignore
        except ImportError:
            return {str(symbol)}
    try:
        return aliases_for(symbol) or {str(symbol)}
    except Exception:
        return {str(symbol)}


def _marker_for_symbol(symbol: str, markers: dict[str, dict]) -> Optional[dict]:
    aliases = _aliases_for_symbol(symbol)
    candidates: list[str] = []
    for a in aliases:
        candidates.append(a)
        candidates.append(str(a).replace("/", "_").replace(" ", "_"))
    # Prefer the canonical key first, then alias forms.
    for k in candidates:
        if k in markers:
            return markers[k]
    return None


def _retry_storm_active(now: Optional[datetime] = None) -> bool:
    """True iff any Alpaca 4xx event in the last RETRY_STORM_WINDOW_MINUTES."""
    cutoff = (now or _now()) - timedelta(minutes=RETRY_STORM_WINDOW_MINUTES)
    d = _audit_dir()
    if not d.exists():
        return False
    # Scan only today + yesterday — 60-minute window won't escape that.
    for delta in (0, 1):
        day = ((now or _now()) - timedelta(days=delta)).date().isoformat()
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
                    errors = row.get("errors") or []
                    err_str = " | ".join(str(e) for e in (errors if isinstance(errors, list) else []))
                    if not any(s in reason or s in err_str for s in (
                        "Alpaca 403", "Alpaca 422", "insufficient balance",
                        "qty must be > 0", "held_for_orders",
                    )):
                        continue
                    ts = _parse_iso(row.get("timestamp") or row.get("ts_iso"))
                    if ts is None:
                        continue
                    if ts >= cutoff:
                        return True
        except OSError:
            continue
    return False


# ── Per-symbol evaluator ──────────────────────────────────────────────────────

@dataclass
class SymbolClearance:
    symbol: str
    verdict: str
    detail: str
    marker_path: Optional[str] = None
    marker_iso: Optional[str] = None
    last_failure_iso: Optional[str] = None
    aliases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _evaluate_symbol(symbol: str,
                     markers: dict[str, dict],
                     *,
                     safe_mode_blocked: bool,
                     equity_gap_blocked: bool,
                     storm_active: bool) -> SymbolClearance:
    aliases = sorted(_aliases_for_symbol(symbol))

    if equity_gap_blocked:
        return SymbolClearance(
            symbol=symbol,
            verdict=V_EQUITY_GAP,
            detail="equity_gap not OK — block this symbol's clearance",
            aliases=aliases,
        )

    if safe_mode_blocked:
        return SymbolClearance(
            symbol=symbol,
            verdict=V_SAFE_MODE,
            detail="safe_mode consistency NOT clean — block this symbol's clearance",
            aliases=aliases,
        )

    marker = _marker_for_symbol(symbol, markers)
    if marker is None:
        return SymbolClearance(
            symbol=symbol,
            verdict=V_NO_MARKER,
            detail=f"no operator-confirmation marker for any alias of {symbol}",
            aliases=aliases,
        )

    marker_ts_iso = str(marker.get("timestamp_iso") or "")
    marker_ts = _parse_iso(marker_ts_iso)

    failures = _scan_audit_for_symbol_failures(
        symbol=symbol,
        aliases=set(aliases),
        lookback_hours=FRESH_FAILURE_LOOKBACK_HOURS,
    )
    failures_before_marker: list[tuple[datetime, dict]] = []
    failures_after_marker:  list[tuple[datetime, dict]] = []
    if marker_ts is not None:
        for ts, row in failures:
            if ts < marker_ts:
                failures_before_marker.append((ts, row))
            else:
                failures_after_marker.append((ts, row))
    last_failure_ts: Optional[datetime] = failures[-1][0] if failures else None

    # PRECEDENCE NOTE
    # We distinguish two adjacent verdicts deliberately:
    #
    # * MARKER_BEFORE_FAILURE — the operator marker predates EVERY known
    #   failure in the lookback window. There has never been a clean
    #   state since the marker was written; the marker is stale.
    # * FRESH_FAILURE — the marker came AFTER at least one earlier
    #   failure (so the operator was reacting to a known issue) but a
    #   *new* failure has happened after the marker, invalidating the
    #   clean state the marker promised.
    #
    # When marker_ts equals the only failure timestamp we fall through
    # to V_READY because that's effectively "marker recorded as part of
    # closing the failure".

    if (marker_ts is not None
            and last_failure_ts is not None
            and not failures_before_marker
            and last_failure_ts > marker_ts):
        # Every failure in the window is after the marker → marker is
        # stale; the operator confirmation has never been valid.
        return SymbolClearance(
            symbol=symbol,
            verdict=V_MARKER_BEFORE_FAILURE,
            detail=(f"marker {marker_ts.isoformat()} predates every failure "
                    f"in the lookback window; last failure at "
                    f"{last_failure_ts.isoformat()}"),
            marker_iso=marker_ts.isoformat(),
            last_failure_iso=last_failure_ts.isoformat(),
            aliases=aliases,
        )

    if failures_after_marker:
        # Marker was good for the earlier failures, but a fresh one
        # invalidated it.
        last_after = failures_after_marker[-1][0]
        return SymbolClearance(
            symbol=symbol,
            verdict=V_FRESH_FAILURE,
            detail=(f"failure at {last_after.isoformat()} occurred after "
                    f"operator marker {marker_ts.isoformat() if marker_ts else '?'}"),
            marker_iso=marker_ts_iso or None,
            last_failure_iso=last_after.isoformat(),
            aliases=aliases,
        )

    # Storm active (system-wide) — block as a precaution.
    if storm_active:
        return SymbolClearance(
            symbol=symbol,
            verdict=V_FRESH_FAILURE,
            detail=("retry-storm activity detected in last "
                    f"{RETRY_STORM_WINDOW_MINUTES} minutes — wait for "
                    "broker to be quiet"),
            marker_iso=marker_ts_iso or None,
            last_failure_iso=(last_failure_ts.isoformat()
                              if last_failure_ts else None),
            aliases=aliases,
        )

    return SymbolClearance(
        symbol=symbol,
        verdict=V_READY,
        detail=f"all preconditions met — marker={marker_ts_iso}",
        marker_iso=marker_ts_iso or None,
        last_failure_iso=(last_failure_ts.isoformat() if last_failure_ts else None),
        aliases=aliases,
    )


# ── Top-level evaluator ───────────────────────────────────────────────────────

@dataclass
class ClearanceReport:
    schema_version: str
    evaluated_at_iso: str
    blocked_symbols: list[str]
    per_symbol: list[dict]
    all_ready: bool
    safe_mode_blocked: bool
    equity_gap_blocked: bool
    storm_active: bool
    proposal_path: Optional[str]
    proposed_actions: list[str]
    standing_markers: list[str]


def _standing_markers() -> list[str]:
    return [
        "EDGE_GATE_ENABLED=false",
        "ALLOW_BROKER_PAPER=false",
        "LIVE_TRADING_UNSUPPORTED",
        "NO_ORDER_PLACEMENT",
        "NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT",
    ]


def _evaluate_all(*, apply_mode: bool) -> ClearanceReport:
    brr_entries = _read_broker_repair_state()
    blocked_symbols = sorted(brr_entries.keys())

    sm_verdict, _ = _read_safe_mode_consistency_verdict()
    sm_runtime_active = _read_runtime_safe_mode_active()
    # Safe-mode "blocked" iff inconsistent OR runtime says active.
    safe_mode_blocked = (
        sm_verdict not in ("", "CONSISTENT") or sm_runtime_active
    )

    equity_verdict = _read_equity_gap_verdict()
    equity_gap_blocked = bool(equity_verdict) and equity_verdict != "EQUITY_GAP_OK"

    markers = _read_operator_markers()
    storm_active = _retry_storm_active()

    per_symbol: list[SymbolClearance] = []
    for sym in blocked_symbols:
        per_symbol.append(_evaluate_symbol(
            sym, markers,
            safe_mode_blocked=safe_mode_blocked,
            equity_gap_blocked=equity_gap_blocked,
            storm_active=storm_active,
        ))

    all_ready = bool(blocked_symbols) and all(s.verdict == V_READY for s in per_symbol)

    proposal_path: Optional[Path] = None
    proposed_actions: list[str] = []

    if all_ready:
        # Build textual operator-readable action list.
        for s in per_symbol:
            proposed_actions.append(
                f"Operator: invoke shared.broker_repair_required.clear_repair("
                f"'{s.symbol}', marker_path='<absolute path of "
                f"learning-loop/operator_markers/{s.symbol.replace('/', '_')}_<date>.json>') "
                "only after operator review."
            )
        if apply_mode:
            proposal_path = _write_proposal(per_symbol, proposed_actions)

    return ClearanceReport(
        schema_version="v3.31",
        evaluated_at_iso=_now_iso(),
        blocked_symbols=blocked_symbols,
        per_symbol=[s.to_dict() for s in per_symbol],
        all_ready=all_ready,
        safe_mode_blocked=safe_mode_blocked,
        equity_gap_blocked=equity_gap_blocked,
        storm_active=storm_active,
        proposal_path=str(proposal_path) if proposal_path else None,
        proposed_actions=proposed_actions,
        standing_markers=_standing_markers(),
    )


# ── Writer ────────────────────────────────────────────────────────────────────

def _write_proposal(per_symbol: list[SymbolClearance], actions: list[str]) -> Path:
    path = _proposal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version":     "v3.31",
        "type":               "broker_repair_clearance_proposal",
        "evaluated_at_iso":   _now_iso(),
        "per_symbol":         [s.to_dict() for s in per_symbol],
        "proposed_actions":   actions,
        "note":               (
            "This file is a PROPOSAL only. It does NOT clear any symbol. "
            "The operator must invoke shared.broker_repair_required.clear_repair "
            "manually with the matching marker path."
        ),
        "standing_markers":   _standing_markers(),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(body, fh, indent=2, sort_keys=True)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp, path)
    return path


# ── CLI ───────────────────────────────────────────────────────────────────────

def _str_to_bool(s: str) -> bool:
    return str(s).strip().lower() in {"1", "true", "yes", "on"}


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="propose_clear_broker_repair_canonical.py",
        description=(
            "Propose (do NOT execute) per-symbol broker_repair_required "
            "clearance steps. Default DRY-RUN. Pass --apply --operator-confirmed "
            "to WRITE the proposal file (operator still executes the clears "
            "via shared.broker_repair_required.clear_repair)."
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
    apply_mode = bool(args.apply) and bool(args.operator_confirmed) and not dry_run_flag

    report = _evaluate_all(apply_mode=apply_mode)

    if bool(args.apply) and not bool(args.operator_confirmed):
        print("REFUSED: --apply requires --operator-confirmed. Run with both flags "
              "to write the proposal file. The proposal NEVER auto-clears.")

    print(f"propose_clear_broker_repair_canonical: blocked_symbols={report.blocked_symbols}")
    print(f"  safe_mode_blocked={report.safe_mode_blocked}  "
          f"equity_gap_blocked={report.equity_gap_blocked}  "
          f"storm_active={report.storm_active}")
    for s in report.per_symbol:
        print(f"  - {s['symbol']:10s}  verdict={s['verdict']}  detail={s['detail']}")
    print(f"  all_ready={report.all_ready}")
    if report.proposal_path:
        print(f"  PROPOSAL WRITTEN: {report.proposal_path}")
    elif report.all_ready and not apply_mode:
        print("  (dry-run — pass --apply --operator-confirmed to write proposal)")
    for m in report.standing_markers:
        print(f"  marker: {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "V_NO_MARKER",
    "V_MARKER_BEFORE_FAILURE",
    "V_FRESH_FAILURE",
    "V_SAFE_MODE",
    "V_EQUITY_GAP",
    "V_READY",
    "V_PROPOSAL_WRITTEN",
    "SymbolClearance",
    "ClearanceReport",
    "main",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT",
    "EDGE_GATE_ENABLED",
    "ALLOW_BROKER_PAPER",
]
