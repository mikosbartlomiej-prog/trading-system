"""v3.30 ETAP 4 (2026-06-16) — Canonical safe_mode state persistence.

WHY THIS EXISTS
---------------
v3.28 + v3.29 production observed a critical persistence bug: the
incident-pattern-detector emitted 46 ``SAFE_MODE_ENTERED`` audit events
in 48 hours (one per detector tick on the AVAX/USD P13 retry storm)
BUT ``learning-loop/runtime_state.json::safe_mode`` was still inactive
the next morning. The allocator therefore saw safe_mode inactive and
was free to deploy fresh capital — exactly the failure mode the gate
was supposed to prevent.

Root cause: ``shared/safe_mode.enter_safe_mode`` writes to
``runtime_state.json`` via ``runtime_state.write_section``. That file
is only committed by the exit-monitor workflow's post-step that runs
``git add learning-loop/runtime_state.json``. When (a) the workflow
that emitted the audit row was NOT exit-monitor and (b) the next
exit-monitor tick happened after the cron that read the state — the
runtime payload existed on the runner's disk but never landed on
``origin/main``. The next workflow checkout reset the file to whatever
``main`` had, which was ``null``.

THE FIX
-------
This module adds a SECOND canonical persistence file:

    learning-loop/safe_mode_state.json

owned by safe_mode itself (not by an unrelated workflow). All writes
are atomic (tmp + fsync + ``os.replace``) and ``read_active_state``
treats either file as authoritative: if EITHER says active, the
system is in safe_mode. This survives both the original race AND any
new workflow that forgets to commit ``runtime_state.json``.

It also mirrors the payload into ``runtime_state.safe_mode`` for
backward compatibility — every existing reader still sees the right
answer. ``safe_mode_state.json`` is the new primary truth.

HARD INVARIANTS (do not loosen)
-------------------------------
* This module NEVER imports ``alpaca_orders``.
* This module NEVER calls ``submit_order`` / ``place_order`` /
  ``safe_close`` / ``cancel_order`` / ``close_position``.
* This module NEVER makes network calls.
* This module NEVER auto-clears safe_mode. Only ``propose_exit`` may
  run, and it never mutates the state file — it only writes a
  PROPOSAL marker to ``learning-loop/operator_markers/`` for the
  operator to review.
* This module NEVER flips ``LIVE_TRADING`` / ``ALLOW_BROKER_PAPER`` /
  ``EDGE_GATE_ENABLED``.
* Writes are atomic and fail-CLOSED: a write failure raises so the
  caller knows safe_mode could not be persisted.
* The consistency rule between this file and the audit JSONL is
  REPORTED ONLY (see ``v3.29 scripts/check_safe_mode_consistency.py``).
  This module never silently auto-recovers a mismatch.

STANDING MARKERS
----------------
- ``EDGE_GATE_ENABLED=false``
- ``ALLOW_BROKER_PAPER=false``
- ``LIVE_TRADING_UNSUPPORTED``
- ``NO_ORDER_PLACEMENT``
- ``NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE``
- ``NO_AUTO_SAFE_MODE_CLEAR``
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Standing invariants (asserted by tests) ───────────────────────────────────
LIVE_TRADING_UNSUPPORTED = True
NO_ORDER_PLACEMENT = True
NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE = True
NO_AUTO_SAFE_MODE_CLEAR = True
EDGE_GATE_ENABLED = False
ALLOW_BROKER_PAPER = False

# Dedupe: same (trigger, symbol) within this window is treated as already
# active. Stops detector spam without losing the first event.
DEDUPE_WINDOW_SECONDS = 600


_REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Paths ────────────────────────────────────────────────────────────────────

def _state_path() -> Path:
    env = os.environ.get("SAFE_MODE_STATE_PATH")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "safe_mode_state.json"


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


# ── Dataclass ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CanonicalSafeModeState:
    """Frozen record of safe_mode state, persisted to safe_mode_state.json."""

    active: bool
    trigger: str
    reason: str
    symbol: str  # empty string when not symbol-scoped
    entered_at_iso: str
    last_updated_iso: str
    forced_by_operator: bool = False
    schema_version: str = "v3.30"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def inactive(cls) -> "CanonicalSafeModeState":
        ts = _now_iso()
        return cls(
            active=False,
            trigger="",
            reason="",
            symbol="",
            entered_at_iso="",
            last_updated_iso=ts,
            forced_by_operator=False,
        )

    @classmethod
    def from_dict(cls, raw: dict) -> "CanonicalSafeModeState":
        return cls(
            active=bool(raw.get("active", False)),
            trigger=str(raw.get("trigger", "") or ""),
            reason=str(raw.get("reason", "") or ""),
            symbol=str(raw.get("symbol", "") or ""),
            entered_at_iso=str(raw.get("entered_at_iso", "") or ""),
            last_updated_iso=str(raw.get("last_updated_iso", "") or ""),
            forced_by_operator=bool(raw.get("forced_by_operator", False)),
            schema_version=str(raw.get("schema_version", "v3.30") or "v3.30"),
        )


class SafeModeStateWriteFailed(RuntimeError):
    """Raised when the canonical state file could NOT be persisted.

    Per the v3.30 fail-CLOSED contract, callers MUST surface this so
    they know safe_mode is in an undefined-on-disk state. Do NOT
    silently catch.
    """


# ── Atomic I/O ────────────────────────────────────────────────────────────────

def _atomic_write_json(path: Path, payload: dict) -> None:
    """Atomic JSON write: tmp file + flush + fsync + os.replace.

    Raises SafeModeStateWriteFailed on any I/O error; the caller is
    responsible for surfacing the failure (per fail-CLOSED contract).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                # fsync may not be supported on test tmpfs — ignore.
                pass
        os.replace(tmp, path)
    except OSError as e:
        raise SafeModeStateWriteFailed(
            f"safe_mode_state: atomic write to {path} failed: {e}"
        ) from e


def _read_json(path: Path) -> dict:
    """Tolerant JSON read; returns {} on any error."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


# ── Public API: read ─────────────────────────────────────────────────────────

def read_canonical_state() -> CanonicalSafeModeState:
    """Read the canonical safe_mode_state.json file.

    Returns inactive when the file is missing or empty.
    """
    raw = _read_json(_state_path())
    if not raw:
        return CanonicalSafeModeState.inactive()
    return CanonicalSafeModeState.from_dict(raw)


def read_runtime_mirror() -> dict:
    """Read the legacy runtime_state.json::safe_mode mirror (best-effort).

    Imported lazily so this module stays free of runtime_state when
    callers patch SAFE_MODE_STATE_PATH for tests.
    """
    try:
        try:
            from runtime_state import read_section  # type: ignore
        except ImportError:
            from shared.runtime_state import read_section  # type: ignore
        out = read_section("safe_mode")
        return out if isinstance(out, dict) else {}
    except Exception:
        return {}


def is_active() -> bool:
    """True if EITHER the canonical state file or the runtime mirror is active.

    This is the contract that defends against the v3.29 persistence bug.
    If the runtime mirror ever desyncs from the canonical file, the
    union of the two is the truth — never the intersection.
    """
    if read_canonical_state().active:
        return True
    return bool(read_runtime_mirror().get("active", False))


def current_state() -> CanonicalSafeModeState:
    """Return the canonical state, but flip to ACTIVE if the runtime mirror
    says active and the canonical file does not.

    This handles the legacy case where another process wrote to the
    runtime mirror without touching the canonical file. The canonical
    file remains the WRITE primary; this helper just guarantees no
    reader misses an active runtime mirror.
    """
    canonical = read_canonical_state()
    if canonical.active:
        return canonical
    mirror = read_runtime_mirror()
    if mirror.get("active"):
        # Synthesize a CanonicalSafeModeState from the mirror payload.
        return CanonicalSafeModeState(
            active=True,
            trigger=str(mirror.get("trigger") or "OPERATOR"),
            reason=str(mirror.get("reason") or "runtime mirror reports active without canonical state"),
            symbol=str(mirror.get("symbol") or ""),
            entered_at_iso=str(mirror.get("entered_at") or _now_iso()),
            last_updated_iso=_now_iso(),
            forced_by_operator=bool(mirror.get("forced", False)),
        )
    return canonical


# ── Public API: write (enter) ────────────────────────────────────────────────

def _seconds_between(later_iso: str, earlier_iso: str) -> Optional[float]:
    try:
        a = datetime.fromisoformat(later_iso.replace("Z", "+00:00"))
        b = datetime.fromisoformat(earlier_iso.replace("Z", "+00:00"))
        return (a - b).total_seconds()
    except (TypeError, ValueError):
        return None


def _mirror_to_runtime(state: CanonicalSafeModeState, *, actor: str) -> None:
    """Best-effort mirror to runtime_state.json::safe_mode.

    Failure here is logged but does NOT raise; the canonical file is
    the primary truth. We don't want a runtime_state write failure to
    break safe_mode persistence.
    """
    try:
        try:
            from runtime_state import write_section  # type: ignore
        except ImportError:
            from shared.runtime_state import write_section  # type: ignore
        # Match the legacy mirror schema used by shared/safe_mode.py.
        mirror = {
            "active":     state.active,
            "reason":     state.reason,
            "entered_at": state.entered_at_iso,
            "trigger":    state.trigger,
            "forced":     state.forced_by_operator,
            "symbol":     state.symbol,
        }
        write_section("safe_mode", mirror, actor=actor)
    except Exception as e:
        # Fail-soft on mirror — canonical is what counts.
        print(f"  safe_mode_state: mirror to runtime failed (non-fatal): {e}")


def _emit_audit_recovery_required(canonical_active: bool,
                                  mirror_active: bool) -> None:
    """Best-effort emit of a SAFE_MODE_STATE_RECOVERY_REQUIRED row.

    Only used when an inconsistency is detected. Never auto-recovers.
    """
    try:
        d = _audit_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{_today_iso_date()}.jsonl"
        row = {
            "decision_type":  "SAFE_MODE_STATE_RECOVERY_REQUIRED",
            "actor":          "safe_mode_state",
            "reason":         (
                "audit/state inconsistency: canonical_active="
                f"{canonical_active} mirror_active={mirror_active} — operator "
                "review required, no auto-recovery"
            ),
            "ts_iso":         _now_iso(),
            "reversible":     True,
            "status":         "placed",
        }
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    except OSError:
        return


def _emit_audit_write_failed(trigger: str, reason: str, exc: BaseException) -> None:
    """Best-effort audit row for SAFE_MODE_STATE_WRITE_FAILED."""
    try:
        d = _audit_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{_today_iso_date()}.jsonl"
        row = {
            "decision_type":  "SAFE_MODE_STATE_WRITE_FAILED",
            "actor":          "safe_mode_state",
            "reason":         f"trigger={trigger} reason={reason} exc={type(exc).__name__}: {exc}",
            "ts_iso":         _now_iso(),
            "reversible":     False,
            "status":         "failed",
        }
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    except OSError:
        return


def _emit_audit_entered(state: CanonicalSafeModeState) -> None:
    """Best-effort SAFE_MODE_STATE_ENTERED audit row (canonical-state path)."""
    try:
        d = _audit_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{_today_iso_date()}.jsonl"
        row = {
            "decision_type":  "SAFE_MODE_STATE_ENTERED",
            "actor":          "safe_mode_state",
            "reason":         state.reason,
            "trigger":        state.trigger,
            "symbol":         state.symbol,
            "entered_at_iso": state.entered_at_iso,
            "ts_iso":         _now_iso(),
            "reversible":     True,
            "status":         "placed",
        }
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    except OSError:
        return


def enter(*,
          trigger: str,
          reason: str,
          symbol: str = "",
          actor: str = "safe_mode_state",
          dedupe_seconds: float = DEDUPE_WINDOW_SECONDS,
          ) -> CanonicalSafeModeState:
    """Flip safe_mode ON with atomic canonical-state persistence.

    Behaviour:

    1. Compute (trigger, symbol) and check whether a current state
       with the SAME trigger+symbol exists and is within
       ``dedupe_seconds``. If so, no-op and return the existing
       state (no double-write, no fresh audit).
    2. Otherwise write a fresh CanonicalSafeModeState atomically:
         - safe_mode_state.json (primary truth)
         - runtime_state.json::safe_mode (best-effort mirror)
    3. Emit one SAFE_MODE_STATE_ENTERED audit row.
    4. If the atomic write fails, raise SafeModeStateWriteFailed
       and emit SAFE_MODE_STATE_WRITE_FAILED audit row first. This
       is the fail-CLOSED behaviour: callers MUST know safe_mode
       could not be persisted.

    Returns the new (or existing on dedupe) CanonicalSafeModeState.
    """
    if not trigger:
        raise ValueError("safe_mode_state.enter: trigger cannot be empty")
    if not reason:
        raise ValueError("safe_mode_state.enter: reason cannot be empty")

    existing = read_canonical_state()

    # Dedupe: same trigger + same symbol within window → no-op.
    if (
        existing.active
        and existing.trigger == trigger
        and existing.symbol == (symbol or "")
        and existing.entered_at_iso
    ):
        age = _seconds_between(_now_iso(), existing.entered_at_iso)
        if age is not None and age < float(dedupe_seconds):
            return existing

    new_state = CanonicalSafeModeState(
        active=True,
        trigger=trigger,
        reason=reason,
        symbol=symbol or "",
        entered_at_iso=existing.entered_at_iso if (
            existing.active and existing.trigger == trigger
            and existing.symbol == (symbol or "")
        ) else _now_iso(),
        last_updated_iso=_now_iso(),
        forced_by_operator=existing.forced_by_operator,
    )

    try:
        _atomic_write_json(_state_path(), new_state.to_dict())
    except SafeModeStateWriteFailed as e:
        _emit_audit_write_failed(trigger, reason, e)
        raise

    _mirror_to_runtime(new_state, actor=actor)
    _emit_audit_entered(new_state)
    return new_state


# ── Public API: consistency / operator marker ────────────────────────────────

def check_consistency_with_audit() -> dict:
    """Compare canonical state to runtime mirror and emit a
    SAFE_MODE_STATE_RECOVERY_REQUIRED audit row when they disagree.

    Reports ONLY — never auto-recovers. Returns a dict describing
    the comparison for caller inspection / logging.
    """
    canonical = read_canonical_state()
    mirror_raw = read_runtime_mirror()
    mirror_active = bool(mirror_raw.get("active", False))

    report = {
        "canonical_active":   canonical.active,
        "canonical_trigger":  canonical.trigger,
        "mirror_active":      mirror_active,
        "mirror_trigger":     str(mirror_raw.get("trigger") or ""),
        "consistent":         canonical.active == mirror_active,
        "evaluated_at_iso":   _now_iso(),
    }
    if not report["consistent"]:
        _emit_audit_recovery_required(canonical.active, mirror_active)
        report["recovery_required"] = True
    else:
        report["recovery_required"] = False
    return report


# ── Public API: NEVER auto-clears safe_mode ──────────────────────────────────
#
# There is no public ``exit()`` / ``clear()`` function in this module.
# The legacy ``shared/safe_mode.exit_safe_mode`` remains for backward
# compatibility but does NOT touch the canonical state file. Operator
# clearance flows through ``scripts/propose_clear_broker_repair_and_safe_mode.py``,
# which writes a PROPOSAL marker that the operator must apply
# manually. This is enforced by the test
# ``test_no_auto_clear_from_any_code_path`` and by the AST scan.


__all__ = [
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE",
    "NO_AUTO_SAFE_MODE_CLEAR",
    "EDGE_GATE_ENABLED",
    "ALLOW_BROKER_PAPER",
    "DEDUPE_WINDOW_SECONDS",
    "CanonicalSafeModeState",
    "SafeModeStateWriteFailed",
    "read_canonical_state",
    "read_runtime_mirror",
    "is_active",
    "current_state",
    "enter",
    "check_consistency_with_audit",
]
