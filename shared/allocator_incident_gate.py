"""v3.28 ETAP 3 + 8 (2026-06-16) — Allocator-side incident gate.

CONTAINMENT MODULE — read this before changing anything.

PURPOSE
-------
Block the morning allocator from deploying fresh capital while any
active incident is unresolved. This is the gate that closes the gap
discovered in the 2026-06-15 AVAXUSD P13 storm: safe_mode was
entered by the detector but never persisted to runtime_state, so
the allocator was still free to BUY into a broken broker session.

This gate is the second line of defence (the first is safe_mode
itself when it does persist). It fails CLOSED on any check error.

CONTRACT (do not loosen)
------------------------
* Default decision is ``BLOCK_UNKNOWN``. Only an affirmative pass on
  every single check escalates to ``ALLOW_ALLOCATOR``.
* This module NEVER calls the broker.
* This module NEVER imports ``alpaca_orders``.
* This module NEVER places orders.
* Any check raising → BLOCK_UNKNOWN (fail CLOSED).

CHECKS (in order)
-----------------
1. ``safe_mode.read_state`` → if active → BLOCK_SAFE_MODE_ACTIVE.
2. ``broker_repair_required.load_state`` → if any blocked symbols →
   BLOCK_BROKER_REPAIR_REQUIRED.
3. ``incident_pattern_detector`` latest output → if active P13
   today → BLOCK_P13_ACTIVE.
4. ``equity_gap_reconciliation`` report → if gap percent > 2 →
   BLOCK_EQUITY_GAP_UNRESOLVED.
5. Position reconciliation timestamp → if stale > 2h during US
   market hours → BLOCK_POSITION_RECONCILIATION_STALE.
6. Kill-switch flag → if active → BLOCK_KILL_SWITCH.
7. Everything clear → ALLOW_ALLOCATOR.

USAGE FROM ALLOCATOR
--------------------
At the very top of ``scripts/execute_allocation_plan.py::main()``::

    from allocator_incident_gate import evaluate, AllocatorIncidentDecision
    result = evaluate()
    if result.decision is not AllocatorIncidentDecision.ALLOW_ALLOCATOR:
        write_audit_decision(result)
        write_block_doc(result, date=today)
        return 0  # clean exit, no orders placed

NEVER place orders if the gate is not ``ALLOW_ALLOCATOR``.
NEVER clear safe_mode from the allocator.
"""

from __future__ import annotations

import enum
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Decision enum ─────────────────────────────────────────────────────────────

class AllocatorIncidentDecision(enum.Enum):
    """Possible verdicts from ``evaluate``.

    Order is significant for tests — BLOCK_UNKNOWN is the safest fallback
    and is the default when ANY check raises an exception. ALLOW_ALLOCATOR
    is the ONLY non-blocking value.
    """

    ALLOW_ALLOCATOR = "ALLOW_ALLOCATOR"
    BLOCK_SAFE_MODE_ACTIVE = "BLOCK_SAFE_MODE_ACTIVE"
    BLOCK_SAFE_MODE_INCONSISTENT = "BLOCK_SAFE_MODE_INCONSISTENT"
    BLOCK_BROKER_REPAIR_REQUIRED = "BLOCK_BROKER_REPAIR_REQUIRED"
    BLOCK_P13_ACTIVE = "BLOCK_P13_ACTIVE"
    BLOCK_EQUITY_GAP_UNRESOLVED = "BLOCK_EQUITY_GAP_UNRESOLVED"
    BLOCK_EQUITY_GAP_SCHEMA_INVALID = "BLOCK_EQUITY_GAP_SCHEMA_INVALID"
    BLOCK_EQUITY_GAP_STALE = "BLOCK_EQUITY_GAP_STALE"
    BLOCK_POSITION_RECONCILIATION_STALE = "BLOCK_POSITION_RECONCILIATION_STALE"
    BLOCK_KILL_SWITCH = "BLOCK_KILL_SWITCH"
    BLOCK_UNKNOWN = "BLOCK_UNKNOWN"


@dataclass(frozen=True)
class IncidentGateResult:
    decision: AllocatorIncidentDecision
    blockers: tuple[str, ...]
    snapshot: dict
    audit_row: dict


# ── Storage / paths ───────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _audit_dir() -> Path:
    env = os.environ.get("AUDIT_TRADING_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "journal" / "autonomy"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _today_iso_date() -> str:
    return _now().date().isoformat()


# ── Optional inputs (every loader is best-effort) ─────────────────────────────

def _read_safe_mode():
    """Returns a tuple (active: bool, reason: str) or raises on hard error.

    The shared safe_mode module already fails closed on parse error
    (active=True), so we trust its verdict directly.
    """
    try:
        from safe_mode import read_state  # type: ignore
    except ImportError:
        from shared.safe_mode import read_state  # type: ignore
    st = read_state()
    return bool(getattr(st, "active", False)), str(getattr(st, "reason", ""))


def _read_broker_repair():
    try:
        from broker_repair_required import get_blocked_symbols  # type: ignore
    except ImportError:
        from shared.broker_repair_required import get_blocked_symbols  # type: ignore
    return get_blocked_symbols()


def _read_incident_detector_latest() -> dict:
    """Read the most recent incident_pattern_detector output (if any).

    Searches ``learning-loop/incidents/latest.json`` first then falls
    back to today's dated report. Returns {} when nothing is found —
    that case is treated as "no P13 active".
    """
    candidates = [
        _REPO_ROOT / "learning-loop" / "incidents" / "latest.json",
        _REPO_ROOT / "learning-loop" / "incidents" / f"{_today_iso_date()}.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    return json.load(fh) or {}
            except (OSError, json.JSONDecodeError):
                continue
    return {}


def _read_equity_gap_pct() -> Optional[float]:
    """Return the most recent equity-gap percentage (signed, %).

    Reads ``learning-loop/equity_gap_reconciliation_latest.json``. The
    file is produced by ``scripts/reconcile_equity_gap.py``. We accept
    any of {``gap_pct``, ``gap_percent``, ``equity_gap_pct``} as the
    field name. None when missing → treated as unknown.
    """
    candidates = [
        _REPO_ROOT / "learning-loop" / "equity_gap_reconciliation_latest.json",
    ]
    for p in candidates:
        if not p.exists():
            continue
        try:
            with open(p, "r", encoding="utf-8") as fh:
                raw = json.load(fh) or {}
        except (OSError, json.JSONDecodeError):
            continue
        for key in ("gap_pct", "gap_percent", "equity_gap_pct"):
            if key in raw:
                try:
                    return float(raw[key])
                except (TypeError, ValueError):
                    continue
    return None


def _read_equity_gap_report() -> dict:
    """v3.29 ETAP 4 — full equity-gap reconciliation report (raw dict).

    Returns ``{}`` when missing. Callers inspect ``verdict``,
    ``generated_at_iso``, etc. See ``_finalize_equity_gap_decision``.
    """
    p = _REPO_ROOT / "learning-loop" / "equity_gap_reconciliation_latest.json"
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as fh:
            raw = json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _equity_gap_report_stale_seconds(report: dict) -> Optional[float]:
    ts = report.get("generated_at_iso") or report.get("ts_iso")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (_now() - dt).total_seconds()
    except (TypeError, ValueError):
        return None


def _read_safe_mode_consistency() -> dict:
    """v3.29 ETAP 2 — read safe_mode_consistency_latest.json.

    Returns ``{}`` when missing — consumer treats absence as "no
    information" (does not block on its own).
    """
    p = _REPO_ROOT / "learning-loop" / "safe_mode_consistency_latest.json"
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as fh:
            raw = json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _read_position_reconciliation_age_seconds() -> Optional[float]:
    """Read the age of the most recent position reconciliation snapshot.

    Looks for ``learning-loop/position_reconciliation_latest.json`` with
    a ``reconciled_at`` ISO timestamp. Returns seconds-since.
    """
    p = _REPO_ROOT / "learning-loop" / "position_reconciliation_latest.json"
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            raw = json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        return None
    ts = raw.get("reconciled_at") or raw.get("ts_iso")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (_now() - dt).total_seconds()
    except (TypeError, ValueError):
        return None


def _is_us_market_hours(now: Optional[datetime] = None) -> bool:
    """Coarse Mon-Fri 13:30-20:00 UTC check (no holiday calendar).

    Conservative on purpose — used to decide whether a stale position
    reconciliation matters. Outside market hours the gate is more
    lenient and lets the staleness slide.
    """
    n = now or _now()
    if n.weekday() >= 5:
        return False
    minutes = n.hour * 60 + n.minute
    return (13 * 60 + 30) <= minutes <= (20 * 60)


def _read_kill_switch() -> bool:
    """Best-effort kill-switch read.

    Sources tried in order:
      1. ``KILL_SWITCH=true`` environment variable (operator override).
      2. ``config/aggressive_profile.json::kill_switch_armed``.
      3. ``learning-loop/state.json::kill_switch_armed``.
    Any read error → False (do NOT block on a missing kill-switch — we
    rely on the other gates).
    """
    if os.environ.get("KILL_SWITCH", "").strip().lower() in {"1", "true", "yes"}:
        return True

    for rel in ("config/aggressive_profile.json", "learning-loop/state.json"):
        p = _REPO_ROOT / rel
        if not p.exists():
            continue
        try:
            with open(p, "r", encoding="utf-8") as fh:
                raw = json.load(fh) or {}
        except (OSError, json.JSONDecodeError):
            continue
        if bool(raw.get("kill_switch_armed", False)):
            return True
    return False


# ── Core evaluator ────────────────────────────────────────────────────────────

def _make_snapshot() -> dict:
    """Best-effort diagnostic snapshot for the audit row."""
    snap: dict = {"evaluated_at": _now_iso()}
    try:
        active, reason = _read_safe_mode()
        snap["safe_mode_active"] = active
        snap["safe_mode_reason"] = reason
    except Exception as e:
        snap["safe_mode_active"] = None
        snap["safe_mode_error"] = f"{type(e).__name__}: {e}"
    try:
        snap["broker_repair_blocked"] = sorted(_read_broker_repair())
    except Exception as e:
        snap["broker_repair_blocked"] = None
        snap["broker_repair_error"] = f"{type(e).__name__}: {e}"
    try:
        snap["incident_detector_latest"] = _read_incident_detector_latest()
    except Exception as e:
        snap["incident_detector_error"] = f"{type(e).__name__}: {e}"
    snap["equity_gap_pct"] = _read_equity_gap_pct()
    snap["equity_gap_report"] = _read_equity_gap_report()
    snap["safe_mode_consistency"] = _read_safe_mode_consistency()
    snap["position_recon_age_s"] = _read_position_reconciliation_age_seconds()
    snap["is_market_hours"] = _is_us_market_hours()
    try:
        snap["kill_switch_armed"] = _read_kill_switch()
    except Exception as e:
        snap["kill_switch_error"] = f"{type(e).__name__}: {e}"
    return snap


# ── Equity-gap report classification (v3.29 ETAP 4) ───────────────────────────
EQUITY_GAP_STALE_SECONDS = 24 * 3600


def _classify_equity_gap(report: dict) -> tuple[Optional["AllocatorIncidentDecision"], str]:
    """Return (decision_or_None_if_clean, reason_string).

    The function only signals BLOCK conditions — returning ``(None, "")``
    means the report is healthy and the caller may continue.
    """
    if not report:
        # No report on disk → SCHEMA_INVALID (treated as BLOCK by spec).
        return (AllocatorIncidentDecision.BLOCK_EQUITY_GAP_SCHEMA_INVALID,
                "equity_gap_report_missing")

    # Top-level fields required by v3.29 schema.
    required = ("verdict", "generated_at_iso", "block_allocator")
    missing = [k for k in required if k not in report]
    if missing:
        return (AllocatorIncidentDecision.BLOCK_EQUITY_GAP_SCHEMA_INVALID,
                f"equity_gap_schema_missing_keys={','.join(missing)}")

    age = _equity_gap_report_stale_seconds(report)
    if age is None:
        return (AllocatorIncidentDecision.BLOCK_EQUITY_GAP_SCHEMA_INVALID,
                "equity_gap_unparseable_generated_at_iso")
    if age > EQUITY_GAP_STALE_SECONDS:
        return (AllocatorIncidentDecision.BLOCK_EQUITY_GAP_STALE,
                f"equity_gap_stale_seconds={int(age)}")

    verdict = str(report.get("verdict", ""))
    if report.get("block_allocator") is True or verdict == "EQUITY_GAP_UNRESOLVED_BLOCKS_ALLOCATOR":
        return (AllocatorIncidentDecision.BLOCK_EQUITY_GAP_UNRESOLVED,
                f"equity_gap_verdict={verdict}")

    return (None, "")


def evaluate(as_of: Optional[datetime] = None) -> IncidentGateResult:
    """Run every gate check and return a fail-closed decision.

    Default verdict is ``BLOCK_UNKNOWN``. Only when EVERY single check
    affirmatively passes does the verdict escalate to
    ``ALLOW_ALLOCATOR``.
    """
    blockers: list[str] = []
    snapshot: dict = {}
    decision = AllocatorIncidentDecision.BLOCK_UNKNOWN

    try:
        snapshot = _make_snapshot()

        # 1. safe_mode
        sm_active = snapshot.get("safe_mode_active")
        if sm_active is None:
            blockers.append("safe_mode_read_error")
            decision = AllocatorIncidentDecision.BLOCK_UNKNOWN
            return _finalize(decision, blockers, snapshot)
        if sm_active:
            blockers.append("safe_mode_active")
            decision = AllocatorIncidentDecision.BLOCK_SAFE_MODE_ACTIVE
            return _finalize(decision, blockers, snapshot)

        # 1b. safe_mode consistency (v3.29 ETAP 2)
        # If audit shows SAFE_MODE_ENTERED in the recent window but
        # runtime says inactive, the persistence layer dropped the
        # state — block until the operator investigates.
        sm_consistency = snapshot.get("safe_mode_consistency") or {}
        verdict = str(sm_consistency.get("verdict", "")) if isinstance(sm_consistency, dict) else ""
        if verdict == "INCONSISTENT_ENTERED_NOT_PERSISTED":
            blockers.append("safe_mode_consistency=INCONSISTENT_ENTERED_NOT_PERSISTED")
            decision = AllocatorIncidentDecision.BLOCK_SAFE_MODE_INCONSISTENT
            return _finalize(decision, blockers, snapshot)

        # 2. broker_repair_required
        repair = snapshot.get("broker_repair_blocked")
        if repair is None:
            blockers.append("broker_repair_read_error")
            decision = AllocatorIncidentDecision.BLOCK_UNKNOWN
            return _finalize(decision, blockers, snapshot)
        if repair:
            blockers.append(f"broker_repair_required:{','.join(repair)}")
            decision = AllocatorIncidentDecision.BLOCK_BROKER_REPAIR_REQUIRED
            return _finalize(decision, blockers, snapshot)

        # 3. P13 active in latest detector report (today)
        det = snapshot.get("incident_detector_latest") or {}
        if _detector_has_active_p13(det):
            blockers.append("incident_detector_p13_active")
            decision = AllocatorIncidentDecision.BLOCK_P13_ACTIVE
            return _finalize(decision, blockers, snapshot)

        # 4. equity_gap report (v3.29 ETAP 4 — top-level verdict-aware)
        report = snapshot.get("equity_gap_report") or {}
        gap_decision, gap_reason = _classify_equity_gap(report)
        if gap_decision is not None:
            blockers.append(gap_reason)
            decision = gap_decision
            return _finalize(decision, blockers, snapshot)
        # Backward-compat: also keep the percent-based check (a present
        # report passing the schema-check above will already be clean).
        gap = snapshot.get("equity_gap_pct")
        if gap is not None:
            try:
                if abs(float(gap)) > 2.0:
                    blockers.append(f"equity_gap_pct={gap}")
                    decision = AllocatorIncidentDecision.BLOCK_EQUITY_GAP_UNRESOLVED
                    return _finalize(decision, blockers, snapshot)
            except (TypeError, ValueError):
                blockers.append("equity_gap_unparseable")
                decision = AllocatorIncidentDecision.BLOCK_UNKNOWN
                return _finalize(decision, blockers, snapshot)

        # 5. position reconciliation stale > 2h during market hours
        age = snapshot.get("position_recon_age_s")
        is_hours = bool(snapshot.get("is_market_hours"))
        if is_hours and age is not None:
            try:
                if float(age) > 2 * 3600:
                    blockers.append(f"position_recon_stale_s={age}")
                    decision = AllocatorIncidentDecision.BLOCK_POSITION_RECONCILIATION_STALE
                    return _finalize(decision, blockers, snapshot)
            except (TypeError, ValueError):
                blockers.append("position_recon_age_unparseable")
                decision = AllocatorIncidentDecision.BLOCK_UNKNOWN
                return _finalize(decision, blockers, snapshot)

        # 6. kill-switch
        if snapshot.get("kill_switch_armed"):
            blockers.append("kill_switch_armed")
            decision = AllocatorIncidentDecision.BLOCK_KILL_SWITCH
            return _finalize(decision, blockers, snapshot)

        # 7. All clear
        decision = AllocatorIncidentDecision.ALLOW_ALLOCATOR
        return _finalize(decision, blockers, snapshot)

    except Exception as e:
        # Defensive: any uncaught raise from the gate fails CLOSED.
        blockers.append(f"gate_exception:{type(e).__name__}:{e}")
        snapshot.setdefault("gate_exception", f"{type(e).__name__}: {e}")
        return _finalize(AllocatorIncidentDecision.BLOCK_UNKNOWN, blockers, snapshot)


def _detector_has_active_p13(det: dict) -> bool:
    """True iff the detector payload contains an active P13 finding for today."""
    if not isinstance(det, dict):
        return False
    findings = det.get("findings")
    if not isinstance(findings, list):
        return False
    today = _today_iso_date()
    for f in findings:
        if not isinstance(f, dict):
            continue
        pattern = (f.get("pattern") or "").lower()
        severity = (f.get("severity") or "").upper()
        ts = str(f.get("ts_iso") or f.get("first_seen_iso") or "")
        if "p13" in pattern and severity in {"CRITICAL", "WARN", "WARNING"}:
            if not ts or ts.startswith(today):
                return True
    return False


def _finalize(decision: AllocatorIncidentDecision,
              blockers: list[str],
              snapshot: dict) -> IncidentGateResult:
    audit_row = {
        "decision_type":   "ALLOCATOR_INCIDENT_GATE_DECISION",
        "actor":           "allocator_incident_gate",
        "decision":        decision.value,
        "blockers":        list(blockers),
        "snapshot":        snapshot,
        "ts_iso":          _now_iso(),
        "reversible":      True,
        "status":          ("placed"
                            if decision is AllocatorIncidentDecision.ALLOW_ALLOCATOR
                            else "skipped"),
    }
    return IncidentGateResult(
        decision=decision,
        blockers=tuple(blockers),
        snapshot=snapshot,
        audit_row=audit_row,
    )


def write_audit_decision(result: IncidentGateResult) -> Path:
    """Append the gate's verdict to today's audit JSONL."""
    path = _audit_dir() / f"{_today_iso_date()}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(result.audit_row, sort_keys=True, default=str) + "\n")
    return path


__all__ = [
    "AllocatorIncidentDecision",
    "IncidentGateResult",
    "evaluate",
    "write_audit_decision",
]
