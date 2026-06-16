"""v3.29 ETAP 5 (2026-06-16) — System Activation Master Gate.

CONTAINMENT MODULE — read this before changing anything.

PURPOSE
-------
Single unified entry point that decides whether the whole solution is
"safely ON" right now. It composes every deterministic blocker into
ONE verdict so the morning allocator, the operator dashboard, the
audit-board reporters and the system_activation_status builder all
read the same truth.

This is the canonical pre-allocator master gate. ``allocator_incident_gate``
remains live for back-compat (and the allocator continues to wire it in),
but every new caller — dashboards, daily-operator-brief, weekly retro,
shadow simulator — should consume :func:`evaluate` from THIS module.

CONTRACT (do not loosen)
------------------------
* Default decision is ``UNKNOWN_BLOCK_FAIL_CLOSED``. Only an affirmative
  pass on EVERY deterministic check escalates to ``ALLOCATOR_ALLOWED``.
* This module NEVER calls the broker.
* This module NEVER imports ``alpaca_orders``.
* This module NEVER places orders.
* This module NEVER auto-clears ``safe_mode``.
* This module NEVER cancels broker orders.
* LLM advisory status is INFORMATIONAL only. It does NOT block, unblock,
  override, or escalate any deterministic decision.
* Any check raising → ``UNKNOWN_BLOCK_FAIL_CLOSED`` (fail CLOSED).

CHECKS (in order, first BLOCK wins)
-----------------------------------
1. ``safe_mode.read_state`` → if active → ``ALLOCATOR_BLOCKED_SAFE_MODE``.
2. ``safe_mode_consistency_latest.json`` →
   ``INCONSISTENT_ENTERED_NOT_PERSISTED`` →
   ``ALLOCATOR_BLOCKED_SAFE_MODE_INCONSISTENT``.
3. ``broker_repair_required.load_state`` blocked symbols →
   ``ALLOCATOR_BLOCKED_OPERATOR_CONFIRMATION_REQUIRED`` if ANY symbol
   lacks an operator-confirmation marker, otherwise
   ``ALLOCATOR_BLOCKED_BROKER_REPAIR``.
4. ``equity_gap_reconciliation_latest.json`` top-level →
   ``ALLOCATOR_BLOCKED_EQUITY_GAP`` (also handles SCHEMA_INVALID / STALE).
5. Position reconciliation timestamp stale during US market hours →
   ``ALLOCATOR_BLOCKED_POSITION_RECONCILIATION``.
6. Kill-switch armed → ``ALLOCATOR_BLOCKED_KILL_SWITCH``.
7. Everything clear → ``ALLOCATOR_ALLOWED``.

USAGE
-----
::

    from system_activation_gate import evaluate, SystemActivationDecision
    result = evaluate()
    if result.decision is not SystemActivationDecision.ALLOCATOR_ALLOWED:
        write_audit_decision(result)
        return 0  # no orders, no broker calls

STANDING MARKERS
----------------
- ``EDGE_GATE_ENABLED=false``
- ``ALLOW_BROKER_PAPER=false``
- ``LIVE_TRADING_UNSUPPORTED``
- ``NO_ORDER_PLACEMENT``
- ``NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE``
"""

from __future__ import annotations

import enum
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ── Standing invariants (asserted by tests) ───────────────────────────────────
LIVE_TRADING_UNSUPPORTED = True
NO_ORDER_PLACEMENT = True
NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE = True
EDGE_GATE_ENABLED = False
ALLOW_BROKER_PAPER = False

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE",
)

# Equity-gap report freshness — same threshold as allocator_incident_gate.
EQUITY_GAP_STALE_SECONDS = 24 * 3600

# Position reconciliation staleness during market hours (seconds).
POSITION_RECON_STALE_SECONDS = 2 * 3600


REPO_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = REPO_ROOT  # alias kept for internal use


# ── Decision enum (spec §ETAP 5) ──────────────────────────────────────────────

class SystemActivationDecision(enum.Enum):
    """All verdicts emitted by :func:`evaluate`.

    Order is significant: ``UNKNOWN_BLOCK_FAIL_CLOSED`` is the safest
    fallback and is the default when any check raises. The ``SYSTEM_ACTIVE_*``
    values describe the read-only / discovery / shadow modes the system
    sits in while it is NOT executing orders — they are not blockers,
    they are descriptions of the state we ARE in.
    """

    # Affirmative / informational states (no order execution implied)
    SYSTEM_ACTIVE_READ_ONLY        = "SYSTEM_ACTIVE_READ_ONLY"
    SYSTEM_ACTIVE_DISCOVERY_ONLY   = "SYSTEM_ACTIVE_DISCOVERY_ONLY"
    SYSTEM_ACTIVE_SHADOW_ONLY      = "SYSTEM_ACTIVE_SHADOW_ONLY"

    # Allocator verdicts
    ALLOCATOR_ALLOWED                                = "ALLOCATOR_ALLOWED"
    ALLOCATOR_BLOCKED_SAFE_MODE                      = "ALLOCATOR_BLOCKED_SAFE_MODE"
    ALLOCATOR_BLOCKED_BROKER_REPAIR                  = "ALLOCATOR_BLOCKED_BROKER_REPAIR"
    ALLOCATOR_BLOCKED_EQUITY_GAP                     = "ALLOCATOR_BLOCKED_EQUITY_GAP"
    ALLOCATOR_BLOCKED_POSITION_RECONCILIATION        = "ALLOCATOR_BLOCKED_POSITION_RECONCILIATION"
    ALLOCATOR_BLOCKED_KILL_SWITCH                    = "ALLOCATOR_BLOCKED_KILL_SWITCH"
    ALLOCATOR_BLOCKED_SAFE_MODE_INCONSISTENT         = "ALLOCATOR_BLOCKED_SAFE_MODE_INCONSISTENT"
    ALLOCATOR_BLOCKED_OPERATOR_CONFIRMATION_REQUIRED = "ALLOCATOR_BLOCKED_OPERATOR_CONFIRMATION_REQUIRED"

    # Default / catastrophic
    UNKNOWN_BLOCK_FAIL_CLOSED = "UNKNOWN_BLOCK_FAIL_CLOSED"


BLOCKING_DECISIONS: frozenset[SystemActivationDecision] = frozenset({
    SystemActivationDecision.ALLOCATOR_BLOCKED_SAFE_MODE,
    SystemActivationDecision.ALLOCATOR_BLOCKED_BROKER_REPAIR,
    SystemActivationDecision.ALLOCATOR_BLOCKED_EQUITY_GAP,
    SystemActivationDecision.ALLOCATOR_BLOCKED_POSITION_RECONCILIATION,
    SystemActivationDecision.ALLOCATOR_BLOCKED_KILL_SWITCH,
    SystemActivationDecision.ALLOCATOR_BLOCKED_SAFE_MODE_INCONSISTENT,
    SystemActivationDecision.ALLOCATOR_BLOCKED_OPERATOR_CONFIRMATION_REQUIRED,
    SystemActivationDecision.UNKNOWN_BLOCK_FAIL_CLOSED,
})

# Decisions in which shadow simulation is permitted.
# (ALLOCATOR_ALLOWED + SYSTEM_ACTIVE_SHADOW_ONLY — never any BLOCKING_*.)
SHADOW_PERMITTED_DECISIONS: frozenset[SystemActivationDecision] = frozenset({
    SystemActivationDecision.ALLOCATOR_ALLOWED,
    SystemActivationDecision.SYSTEM_ACTIVE_SHADOW_ONLY,
})


@dataclass(frozen=True)
class SystemActivationResult:
    """Frozen verdict + diagnostic context emitted by :func:`evaluate`."""

    decision:           SystemActivationDecision
    blockers:           tuple[str, ...]
    enabled_subsystems: tuple[str, ...]
    llm_status:         str
    snapshot:           dict
    audit_row:          dict
    reason:             str = ""
    standing_markers:   tuple[str, ...] = field(
        default_factory=lambda: STANDING_MARKERS)

    @property
    def diagnostics(self) -> dict:
        """Back-compat alias for the previous ETAP-8 schema."""
        return self.snapshot

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision":           self.decision.value,
            "blockers":           list(self.blockers),
            "enabled_subsystems": list(self.enabled_subsystems),
            "llm_status":         self.llm_status,
            "reason":             self.reason,
            "snapshot":           self.snapshot,
            "audit_row":          self.audit_row,
            "standing_markers":   list(self.standing_markers),
            "shadow_permitted":   self.decision in SHADOW_PERMITTED_DECISIONS,
            "schema_version":     "v3.29",
            "evaluated_at_iso":   _now_iso(),
            "module":             "shared.system_activation_gate",
        }


# ── Path helpers ──────────────────────────────────────────────────────────────

def _audit_dir() -> Path:
    env = os.environ.get("AUDIT_TRADING_DIR")
    if env:
        return Path(env)
    return REPO_ROOT / "journal" / "autonomy"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _today_iso_date() -> str:
    return _now().date().isoformat()


# ── Loader helpers (each best-effort) ─────────────────────────────────────────

def _read_safe_mode() -> tuple[Optional[bool], str]:
    """Return ``(active, reason)``; ``active is None`` means read failed."""
    try:
        try:
            from safe_mode import read_state  # type: ignore
        except ImportError:
            from shared.safe_mode import read_state  # type: ignore
        st = read_state()
        return bool(getattr(st, "active", False)), str(getattr(st, "reason", ""))
    except Exception:
        return None, ""


def _read_safe_mode_consistency() -> dict:
    p = REPO_ROOT / "learning-loop" / "safe_mode_consistency_latest.json"
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as fh:
            raw = json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _read_broker_repair() -> tuple[Optional[set[str]], dict]:
    """Return ``(blocked_symbols_or_None_on_error, raw_state_dict)``."""
    try:
        try:
            from broker_repair_required import get_blocked_symbols, load_state  # type: ignore
        except ImportError:
            from shared.broker_repair_required import get_blocked_symbols, load_state  # type: ignore
        return set(get_blocked_symbols()), {
            sym: entry.to_dict() if hasattr(entry, "to_dict") else dict(entry)
            for sym, entry in load_state().items()
        }
    except Exception:
        return None, {}


def _operator_confirmed_for(symbol: str) -> bool:
    """Best-effort: ``True`` iff a fresh operator-confirmation marker exists."""
    try:
        try:
            from operator_repair_state import has_repair_confirmation  # type: ignore
        except ImportError:
            from shared.operator_repair_state import has_repair_confirmation  # type: ignore
        return bool(has_repair_confirmation(symbol))
    except Exception:
        # Failing the operator-confirmation check fails CLOSED — treat
        # as "no confirmation" so the gate stays on the more-specific
        # ``ALLOCATOR_BLOCKED_OPERATOR_CONFIRMATION_REQUIRED`` decision.
        return False


def _read_equity_gap_report() -> dict:
    p = REPO_ROOT / "learning-loop" / "equity_gap_reconciliation_latest.json"
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as fh:
            raw = json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _equity_gap_age_seconds(report: dict) -> Optional[float]:
    ts = report.get("generated_at_iso") or report.get("ts_iso")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (_now() - dt).total_seconds()
    except (TypeError, ValueError):
        return None


def _classify_equity_gap(report: dict) -> tuple[Optional[SystemActivationDecision], str]:
    """Return ``(BLOCK_decision_or_None_if_clean, reason)``."""
    if not report:
        return (SystemActivationDecision.ALLOCATOR_BLOCKED_EQUITY_GAP,
                "equity_gap_report_missing")

    required = ("verdict", "generated_at_iso", "block_allocator")
    missing = [k for k in required if k not in report]
    if missing:
        return (SystemActivationDecision.ALLOCATOR_BLOCKED_EQUITY_GAP,
                f"equity_gap_schema_missing_keys={','.join(missing)}")

    age = _equity_gap_age_seconds(report)
    if age is None:
        return (SystemActivationDecision.ALLOCATOR_BLOCKED_EQUITY_GAP,
                "equity_gap_unparseable_generated_at_iso")
    if age > EQUITY_GAP_STALE_SECONDS:
        return (SystemActivationDecision.ALLOCATOR_BLOCKED_EQUITY_GAP,
                f"equity_gap_stale_seconds={int(age)}")

    verdict = str(report.get("verdict", ""))
    if (report.get("block_allocator") is True
            or verdict == "EQUITY_GAP_UNRESOLVED_BLOCKS_ALLOCATOR"):
        return (SystemActivationDecision.ALLOCATOR_BLOCKED_EQUITY_GAP,
                f"equity_gap_verdict={verdict}")
    return (None, "")


def _read_position_recon_age_seconds() -> Optional[float]:
    candidates = [
        REPO_ROOT / "learning-loop" / "position_reconciliation_latest.json",
        REPO_ROOT / "learning-loop" / "position_reconciliation" / "latest.json",
    ]
    for p in candidates:
        if not p.exists():
            continue
        try:
            with open(p, "r", encoding="utf-8") as fh:
                raw = json.load(fh) or {}
        except (OSError, json.JSONDecodeError):
            continue
        ts = (raw.get("reconciled_at")
              or raw.get("ts_iso")
              or raw.get("generated_at_iso"))
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            return (_now() - dt).total_seconds()
        except (TypeError, ValueError):
            continue
    return None


def _is_us_market_hours(now: Optional[datetime] = None) -> bool:
    n = now or _now()
    if n.weekday() >= 5:
        return False
    minutes = n.hour * 60 + n.minute
    return (13 * 60 + 30) <= minutes <= (20 * 60)


def _read_kill_switch() -> bool:
    if os.environ.get("KILL_SWITCH", "").strip().lower() in {"1", "true", "yes"}:
        return True
    for rel in ("config/aggressive_profile.json", "learning-loop/state.json"):
        p = REPO_ROOT / rel
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


def _read_llm_status() -> str:
    """Best-effort LLM advisory status read.

    INFORMATIONAL ONLY — never blocks. ``"unavailable"`` when no
    snapshot exists, ``"unknown"`` on read error, otherwise whatever
    string the LLM advisory mesh self-reports.
    """
    p = REPO_ROOT / "learning-loop" / "llm_advisory_mesh_status_latest.json"
    if not p.exists():
        return "unavailable"
    try:
        with open(p, "r", encoding="utf-8") as fh:
            raw = json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        return "unknown"
    if not isinstance(raw, dict):
        return "unknown"
    status = str(raw.get("status") or raw.get("advisory_status") or "")
    return status or "unknown"


# ── Snapshot composer ────────────────────────────────────────────────────────

def _make_snapshot() -> dict:
    snap: dict = {"evaluated_at": _now_iso()}

    active, reason = _read_safe_mode()
    snap["safe_mode_active"] = active
    snap["safe_mode_reason"] = reason

    snap["safe_mode_consistency"] = _read_safe_mode_consistency()

    blocked, raw_state = _read_broker_repair()
    snap["broker_repair_blocked"] = sorted(blocked) if blocked is not None else None
    snap["broker_repair_state"] = raw_state

    snap["equity_gap_report"] = _read_equity_gap_report()

    snap["position_recon_age_s"] = _read_position_recon_age_seconds()
    snap["is_market_hours"] = _is_us_market_hours()

    try:
        snap["kill_switch_armed"] = _read_kill_switch()
    except Exception as e:
        snap["kill_switch_armed"] = None
        snap["kill_switch_error"] = f"{type(e).__name__}: {e}"

    snap["llm_status"] = _read_llm_status()
    return snap


# ── Core evaluator ────────────────────────────────────────────────────────────

def evaluate(as_of: Optional[datetime] = None) -> SystemActivationResult:
    """Run every deterministic check and return a fail-closed verdict.

    The LLM advisory status is recorded but never alters the
    deterministic decision (HARD invariant per spec §HARD).
    """
    blockers: list[str] = []
    snapshot: dict = {}
    decision = SystemActivationDecision.UNKNOWN_BLOCK_FAIL_CLOSED

    # Discovery + shadow always run in read-only mode regardless of the
    # allocator verdict. The dashboard reads these to display "what's
    # still working while we're blocked".
    enabled_subsystems = [
        "discovery_reporters",
        "shadow_simulator",
        "outcome_tracker",
        "operator_dashboard",
    ]

    try:
        snapshot = _make_snapshot()
        llm_status = str(snapshot.get("llm_status") or "unknown")
        reason = ""

        # 1. safe_mode (runtime-operational)
        sm_active = snapshot.get("safe_mode_active")
        if sm_active is None:
            blockers.append("safe_mode_read_error")
            reason = "safe_mode_read_error"
            decision = SystemActivationDecision.UNKNOWN_BLOCK_FAIL_CLOSED
            return _finalize(decision, blockers, enabled_subsystems,
                             llm_status, snapshot, reason)
        if sm_active:
            blockers.append("safe_mode_active")
            reason = f"safe_mode_active: {snapshot.get('safe_mode_reason', '')}"
            decision = SystemActivationDecision.ALLOCATOR_BLOCKED_SAFE_MODE
            return _finalize(decision, blockers, enabled_subsystems,
                             llm_status, snapshot, reason)

        # 2. safe_mode consistency (audit vs persisted runtime)
        sm_consistency = snapshot.get("safe_mode_consistency") or {}
        verdict = (str(sm_consistency.get("verdict", ""))
                   if isinstance(sm_consistency, dict) else "")
        if verdict == "INCONSISTENT_ENTERED_NOT_PERSISTED":
            blockers.append("safe_mode_consistency=INCONSISTENT_ENTERED_NOT_PERSISTED")
            reason = "safe_mode_consistency_INCONSISTENT_ENTERED_NOT_PERSISTED"
            decision = SystemActivationDecision.ALLOCATOR_BLOCKED_SAFE_MODE_INCONSISTENT
            return _finalize(decision, blockers, enabled_subsystems,
                             llm_status, snapshot, reason)

        # 3. broker_repair_required: ANY blocked symbol blocks.
        blocked = snapshot.get("broker_repair_blocked")
        if blocked is None:
            blockers.append("broker_repair_read_error")
            reason = "broker_repair_read_error"
            decision = SystemActivationDecision.UNKNOWN_BLOCK_FAIL_CLOSED
            return _finalize(decision, blockers, enabled_subsystems,
                             llm_status, snapshot, reason)
        if blocked:
            missing_confirmations = [
                s for s in blocked if not _operator_confirmed_for(s)
            ]
            if missing_confirmations:
                blockers.append(
                    f"operator_confirmation_required:{','.join(sorted(missing_confirmations))}"
                )
                reason = (f"operator_confirmation_required={sorted(missing_confirmations)}")
                decision = SystemActivationDecision.ALLOCATOR_BLOCKED_OPERATOR_CONFIRMATION_REQUIRED
                return _finalize(decision, blockers, enabled_subsystems,
                                 llm_status, snapshot, reason)
            blockers.append(f"broker_repair_required:{','.join(sorted(blocked))}")
            reason = f"broker_repair_required={sorted(blocked)}"
            decision = SystemActivationDecision.ALLOCATOR_BLOCKED_BROKER_REPAIR
            return _finalize(decision, blockers, enabled_subsystems,
                             llm_status, snapshot, reason)

        # 4. equity_gap report — top-level verdict-aware classification.
        report = snapshot.get("equity_gap_report") or {}
        gap_decision, gap_reason = _classify_equity_gap(report)
        if gap_decision is not None:
            blockers.append(gap_reason)
            reason = gap_reason
            decision = gap_decision
            return _finalize(decision, blockers, enabled_subsystems,
                             llm_status, snapshot, reason)

        # 5. position reconciliation stale during US market hours.
        age = snapshot.get("position_recon_age_s")
        is_hours = bool(snapshot.get("is_market_hours"))
        if is_hours:
            if age is None:
                blockers.append("position_recon_missing")
                reason = "position_recon_missing_during_market_hours"
                decision = SystemActivationDecision.ALLOCATOR_BLOCKED_POSITION_RECONCILIATION
                return _finalize(decision, blockers, enabled_subsystems,
                                 llm_status, snapshot, reason)
            try:
                if float(age) > POSITION_RECON_STALE_SECONDS:
                    blockers.append(f"position_recon_stale_s={age}")
                    reason = f"position_recon_stale_s={int(age)}"
                    decision = SystemActivationDecision.ALLOCATOR_BLOCKED_POSITION_RECONCILIATION
                    return _finalize(decision, blockers, enabled_subsystems,
                                     llm_status, snapshot, reason)
            except (TypeError, ValueError):
                blockers.append("position_recon_age_unparseable")
                reason = "position_recon_age_unparseable"
                decision = SystemActivationDecision.UNKNOWN_BLOCK_FAIL_CLOSED
                return _finalize(decision, blockers, enabled_subsystems,
                                 llm_status, snapshot, reason)

        # 6. kill-switch armed → hard block.
        if snapshot.get("kill_switch_armed"):
            blockers.append("kill_switch_armed")
            reason = "kill_switch_armed"
            decision = SystemActivationDecision.ALLOCATOR_BLOCKED_KILL_SWITCH
            return _finalize(decision, blockers, enabled_subsystems,
                             llm_status, snapshot, reason)

        # 7. All clear → allocator allowed. Discovery/shadow remain ON.
        decision = SystemActivationDecision.ALLOCATOR_ALLOWED
        return _finalize(decision, blockers, enabled_subsystems,
                         llm_status, snapshot, "all_gates_clear")

    except Exception as e:
        blockers.append(f"gate_exception:{type(e).__name__}:{e}")
        snapshot.setdefault("gate_exception", f"{type(e).__name__}: {e}")
        return _finalize(
            SystemActivationDecision.UNKNOWN_BLOCK_FAIL_CLOSED,
            blockers,
            enabled_subsystems,
            snapshot.get("llm_status", "unknown"),
            snapshot,
            f"gate_exception:{type(e).__name__}:{e}",
        )


def _finalize(decision: SystemActivationDecision,
              blockers: list[str],
              enabled_subsystems: list[str],
              llm_status: str,
              snapshot: dict,
              reason: str = "") -> SystemActivationResult:
    audit_row = {
        "decision_type":          "SYSTEM_ACTIVATION_GATE_DECISION",
        "actor":                  "system_activation_gate",
        "decision":               decision.value,
        "blockers":               list(blockers),
        "enabled_subsystems":     list(enabled_subsystems),
        "llm_status":             llm_status,
        "reason":                 reason,
        "snapshot":               snapshot,
        "ts_iso":                 _now_iso(),
        "reversible":             True,
        "status":                 ("placed"
                                   if decision is SystemActivationDecision.ALLOCATOR_ALLOWED
                                   else "skipped"),
        "standing_markers":       list(STANDING_MARKERS),
        "does_not_execute_orders": True,
    }
    return SystemActivationResult(
        decision=decision,
        blockers=tuple(blockers),
        enabled_subsystems=tuple(enabled_subsystems),
        llm_status=llm_status,
        snapshot=snapshot,
        audit_row=audit_row,
        reason=reason,
    )


def write_audit_decision(result: SystemActivationResult) -> Path:
    """Append the master-gate verdict to today's audit JSONL."""
    path = _audit_dir() / f"{_today_iso_date()}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(result.audit_row, sort_keys=True, default=str) + "\n")
    return path


def shadow_permitted(result: Optional[SystemActivationResult] = None) -> bool:
    """Return True iff shadow simulation is permitted under the verdict."""
    if result is None:
        result = evaluate()
    return result.decision in SHADOW_PERMITTED_DECISIONS


def standing_markers() -> list[str]:
    return list(STANDING_MARKERS)


__all__ = [
    "SystemActivationDecision",
    "SystemActivationResult",
    "BLOCKING_DECISIONS",
    "SHADOW_PERMITTED_DECISIONS",
    "STANDING_MARKERS",
    "evaluate",
    "write_audit_decision",
    "shadow_permitted",
    "standing_markers",
    # invariants
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE",
    "EDGE_GATE_ENABLED",
    "ALLOW_BROKER_PAPER",
]
