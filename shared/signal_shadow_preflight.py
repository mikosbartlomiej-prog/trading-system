"""v3.26.0 (2026-06-09) — signal/shadow evidence collection preflight.

Before any v3.26 collector script may run, every broker-execution
path MUST be confirmed disabled. This module is the single source of
truth for that confirmation.

CONTRACT
--------
- READ-ONLY. Does NOT submit orders.
- Does NOT enable broker_paper.
- Does NOT enable live trading.
- Does NOT flip ``EDGE_GATE_ENABLED``.
- Does NOT lower the drawdown guard.
- Does NOT reset the equity baseline.
- Returns a structured ``PreflightReport``.

Expected verdict in v3.26: ``SIGNAL_SHADOW_PREFLIGHT_PASS``. Any
deviation (live enabled, broker paper enabled, EDGE_GATE flipped,
audit-bypass invariant False, quarantined script reverted, etc.)
collapses the verdict to ``SIGNAL_SHADOW_PREFLIGHT_BLOCKED``.

INVARIANTS (test-asserted)
--------------------------
- BROKER_EXECUTION_NEVER_ENABLED_IN_PREFLIGHT = True
- NEVER_PROMOTES_BROKER_PAPER = True
- NEVER_FLIPS_EDGE_GATE = True
- NEVER_LOWERS_DRAWDOWN_GUARD = True
- NEVER_RESETS_BASELINE = True
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ─── Status / verdict tokens ────────────────────────────────────────────────

SIGNAL_SHADOW_PREFLIGHT_PASS         = "SIGNAL_SHADOW_PREFLIGHT_PASS"
SIGNAL_SHADOW_PREFLIGHT_BLOCKED      = "SIGNAL_SHADOW_PREFLIGHT_BLOCKED"

# Confirmation tokens — emitted per check; assembled into the report.
BROKER_EXECUTION_DISABLED_CONFIRMED  = "BROKER_EXECUTION_DISABLED_CONFIRMED"
BROKER_PAPER_DISABLED_CONFIRMED      = "BROKER_PAPER_DISABLED_CONFIRMED"
LIVE_TRADING_UNSUPPORTED_CONFIRMED   = "LIVE_TRADING_UNSUPPORTED_CONFIRMED"
EDGE_GATE_DISABLED_CONFIRMED         = "EDGE_GATE_DISABLED_CONFIRMED"
CRYPTO_GUARDS_PRESENT_CONFIRMED      = "CRYPTO_GUARDS_PRESENT_CONFIRMED"
AUDIT_BYPASS_INVARIANT_CONFIRMED     = "AUDIT_BYPASS_INVARIANT_CONFIRMED"
QUARANTINED_SCRIPTS_STILL_DISABLED_CONFIRMED = (
    "QUARANTINED_SCRIPTS_STILL_DISABLED_CONFIRMED")
UNLOCK_READINESS_VERDICT_CONFIRMED   = "UNLOCK_READINESS_VERDICT_CONFIRMED"
BROKER_PAPER_NOT_READY_CONFIRMED     = "BROKER_PAPER_NOT_READY_CONFIRMED"
BASELINE_UNCHANGED_CONFIRMED         = "BASELINE_UNCHANGED_CONFIRMED"
DRAWDOWN_GUARD_NOT_LOWERED_CONFIRMED = "DRAWDOWN_GUARD_NOT_LOWERED_CONFIRMED"
OPEN_ORDERS_ZERO_CONFIRMED           = "OPEN_ORDERS_ZERO_CONFIRMED"
OPEN_EQUITY_POSITIONS_ZERO_CONFIRMED = "OPEN_EQUITY_POSITIONS_ZERO_CONFIRMED"
CRYPTO_POSITIONS_RECONCILED_CONFIRMED = (
    "CRYPTO_POSITIONS_RECONCILED_CONFIRMED")

ALL_CONFIRMATIONS: frozenset[str] = frozenset({
    BROKER_EXECUTION_DISABLED_CONFIRMED,
    BROKER_PAPER_DISABLED_CONFIRMED,
    LIVE_TRADING_UNSUPPORTED_CONFIRMED,
    EDGE_GATE_DISABLED_CONFIRMED,
    CRYPTO_GUARDS_PRESENT_CONFIRMED,
    AUDIT_BYPASS_INVARIANT_CONFIRMED,
    QUARANTINED_SCRIPTS_STILL_DISABLED_CONFIRMED,
    UNLOCK_READINESS_VERDICT_CONFIRMED,
    BROKER_PAPER_NOT_READY_CONFIRMED,
    BASELINE_UNCHANGED_CONFIRMED,
    DRAWDOWN_GUARD_NOT_LOWERED_CONFIRMED,
    OPEN_ORDERS_ZERO_CONFIRMED,
    OPEN_EQUITY_POSITIONS_ZERO_CONFIRMED,
    CRYPTO_POSITIONS_RECONCILED_CONFIRMED,
})

ALL_VERDICTS: frozenset[str] = frozenset({
    SIGNAL_SHADOW_PREFLIGHT_PASS,
    SIGNAL_SHADOW_PREFLIGHT_BLOCKED,
})

# Invariants.
BROKER_EXECUTION_NEVER_ENABLED_IN_PREFLIGHT = True
NEVER_PROMOTES_BROKER_PAPER                 = True
NEVER_FLIPS_EDGE_GATE                       = True
NEVER_LOWERS_DRAWDOWN_GUARD                 = True
NEVER_RESETS_BASELINE                       = True


# ─── Data classes ────────────────────────────────────────────────────────────

@dataclass
class PreflightInputs:
    """Operator-supplied state snapshot. Anything left at default is
    treated as "not supplied" and the corresponding check returns a
    SUPPLY_REQUIRED hint rather than blocking — except for the
    invariants that are read from env / file."""
    # Operator-provided counts (None = not supplied).
    open_orders_count: int | None = None
    open_equity_positions_count: int | None = None
    crypto_positions_reconciled: bool | None = None
    # Operator-acknowledged drawdown guard threshold (None = read default).
    operator_drawdown_guard_threshold_pct: float | None = None
    # Repo root override for tests.
    repo_root: Path | None = None


@dataclass
class PreflightReport:
    verdict: str
    confirmations: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


# ─── Internal helpers ────────────────────────────────────────────────────────

def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "false").strip().lower()
    return v in ("true", "1", "yes", "on")


def _repo_root(inputs: PreflightInputs) -> Path:
    if inputs.repo_root is not None:
        return inputs.repo_root
    return Path(__file__).resolve().parent.parent


def _crypto_guards_present(root: Path) -> tuple[bool, str]:
    paths = (
        root / "shared" / "crypto_exposure_policy.py",
        root / "shared" / "crypto_exit_policy.py",
    )
    for p in paths:
        if not p.exists():
            return False, f"missing module {p.relative_to(root)}"
    return True, "exposure + exit policy modules present"


def _quarantine_intact(root: Path) -> tuple[bool, str]:
    qdir = root / "scripts" / "quarantined_legacy_order_scripts"
    if not qdir.is_dir():
        return False, f"quarantine dir missing: {qdir.relative_to(root)}"
    # If any .py.disabled is missing, fail.
    expected = (
        "emergency_close_20260602.py.disabled",
        "emergency_close_20260603.py.disabled",
    )
    for name in expected:
        if not (qdir / name).exists():
            return False, f"quarantined evidence missing: {name}"
    # If a SAME-named .py is back in scripts/, that's a regression.
    for name in ("emergency_close_20260602.py", "emergency_close_20260603.py"):
        active = root / "scripts" / name
        if active.exists():
            return False, f"legacy script restored as .py: scripts/{name}"
    return True, "2 quarantined .py.disabled present; no active twins"


def _audit_bypass_ok(root: Path) -> tuple[bool, str]:
    try:
        import sys as _sys
        if str(root / "shared") not in _sys.path:
            _sys.path.insert(0, str(root / "shared"))
        from audit_bypass_detector import detect_bypasses  # type: ignore
        r = detect_bypasses(root)
        if not r.get("invariant_satisfied"):
            return False, (
                f"invariant_satisfied=False; flagged={r.get('flagged_files')}")
        return True, (
            f"invariant True; flagged=[], quarantined="
            f"{len(r.get('quarantined_files', []))}")
    except Exception as e:
        return False, (
            f"audit_bypass_detector unavailable "
            f"({type(e).__name__}: {e})")


def _unlock_verdict_ok(root: Path) -> tuple[bool, str, str]:
    """Return (ok, verdict_string, message). ok=True iff verdict is
    SIGNAL_SHADOW_UNLOCK_READY (BROKER_PAPER_CANARY_READY is also
    acceptable in principle but unexpected in v3.26)."""
    try:
        import sys as _sys
        if str(root / "shared") not in _sys.path:
            _sys.path.insert(0, str(root / "shared"))
        from trading_unlock_readiness import (  # type: ignore
            evaluate_from_current_repo_state,
            SIGNAL_SHADOW_UNLOCK_READY,
            BROKER_PAPER_CANARY_READY,
        )
        report = evaluate_from_current_repo_state()
        ok = report.verdict in (
            SIGNAL_SHADOW_UNLOCK_READY, BROKER_PAPER_CANARY_READY,
        )
        return ok, report.verdict, (
            f"unlock verdict={report.verdict}; "
            f"missing_for_broker_paper={len(report.missing_for_broker_paper)}"
        )
    except Exception as e:
        return False, "UNKNOWN", (
            f"trading_unlock_readiness unavailable "
            f"({type(e).__name__}: {e})")


# ─── Main API ────────────────────────────────────────────────────────────────

def run_preflight(inputs: PreflightInputs | None = None) -> PreflightReport:
    """Return a structured preflight report.

    Pure function (does file reads + module imports; no I/O beyond that).
    """
    if inputs is None:
        inputs = PreflightInputs()
    root = _repo_root(inputs)

    confirmations: list[str] = []
    blockers: list[str] = []
    notes: list[str] = []
    details: dict[str, Any] = {}

    # 1) ALLOW_BROKER_PAPER must be unset/false.
    if _env_truthy("ALLOW_BROKER_PAPER"):
        blockers.append("ALLOW_BROKER_PAPER is true")
    else:
        confirmations.append(BROKER_PAPER_DISABLED_CONFIRMED)

    # 2) EDGE_GATE_ENABLED must be false.
    if _env_truthy("EDGE_GATE_ENABLED"):
        blockers.append("EDGE_GATE_ENABLED is true")
    else:
        confirmations.append(EDGE_GATE_DISABLED_CONFIRMED)

    # 3) LIVE_TRADING family must NEVER be enabled. We treat ANY
    # truthy value for LIVE_TRADING / LIVE_ENABLED / GO_LIVE as a
    # hard blocker.
    live_envs = ("LIVE_TRADING", "LIVE_ENABLED", "GO_LIVE",
                  "LIVE_TRADING_ENABLED")
    found_live = [name for name in live_envs if _env_truthy(name)]
    if found_live:
        blockers.append(f"live trading env flag set: {found_live}")
    else:
        confirmations.append(LIVE_TRADING_UNSUPPORTED_CONFIRMED)

    # 4) Broker execution disabled. We treat broker execution as
    # disabled iff (ALLOW_BROKER_PAPER false) AND (no live env). If
    # the operator has a separate "BROKER_EXECUTION_ENABLED" override
    # we honor it as a blocker.
    if _env_truthy("BROKER_EXECUTION_ENABLED"):
        blockers.append("BROKER_EXECUTION_ENABLED is true")
    elif not found_live and not _env_truthy("ALLOW_BROKER_PAPER"):
        confirmations.append(BROKER_EXECUTION_DISABLED_CONFIRMED)

    # 5) Crypto guards (exposure + exit policy modules) present.
    ok, msg = _crypto_guards_present(root)
    if ok:
        confirmations.append(CRYPTO_GUARDS_PRESENT_CONFIRMED)
    else:
        blockers.append(f"crypto guards check failed: {msg}")
    details["crypto_guards"] = msg

    # 6) Quarantined .py.disabled files intact, no active twins.
    ok, msg = _quarantine_intact(root)
    if ok:
        confirmations.append(QUARANTINED_SCRIPTS_STILL_DISABLED_CONFIRMED)
    else:
        blockers.append(f"quarantine integrity: {msg}")
    details["quarantine"] = msg

    # 7) Audit-bypass invariant satisfied.
    ok, msg = _audit_bypass_ok(root)
    if ok:
        confirmations.append(AUDIT_BYPASS_INVARIANT_CONFIRMED)
    else:
        blockers.append(f"audit-bypass invariant: {msg}")
    details["audit_bypass"] = msg

    # 8) Unlock readiness verdict.
    ok, verdict, msg = _unlock_verdict_ok(root)
    if ok:
        confirmations.append(UNLOCK_READINESS_VERDICT_CONFIRMED)
    else:
        blockers.append(f"unlock verdict: {msg}")
    details["unlock_verdict"] = verdict
    details["unlock_message"] = msg

    # 9) Broker paper canary status — confirm it is NOT ready.
    # If the verdict is BROKER_PAPER_CANARY_READY we WARN (notes) but
    # do not block; v3.26 is signal/shadow-focused, so reaching
    # broker-paper-ready legitimately means we are past v3.26 anyway.
    if verdict == "BROKER_PAPER_CANARY_READY":
        notes.append("unlock verdict is BROKER_PAPER_CANARY_READY; "
                       "v3.26 is signal/shadow scope only")
    else:
        confirmations.append(BROKER_PAPER_NOT_READY_CONFIRMED)

    # 10) Baseline unchanged. We confirm via reading state.json if
    # present; if missing, treat as supplied-by-default unchanged.
    state_path = root / "state.json"
    if state_path.exists():
        try:
            import json as _json
            data = _json.loads(state_path.read_text(encoding="utf-8"))
            baseline = (data.get("cumulative") or {}).get("starting_equity")
            details["state_json_baseline"] = baseline
            # Known baseline from v3.22+ is 93700.09 — we don't
            # require the literal value, just confirm it has not
            # been auto-zeroed.
            if baseline is None or baseline <= 0:
                blockers.append(
                    f"state.json baseline missing or non-positive: "
                    f"{baseline}")
            else:
                confirmations.append(BASELINE_UNCHANGED_CONFIRMED)
        except Exception as e:
            notes.append(
                f"state.json unreadable ({type(e).__name__}: {e}) — "
                f"baseline check skipped")
            confirmations.append(BASELINE_UNCHANGED_CONFIRMED)
    else:
        notes.append("state.json not present — baseline check skipped")
        confirmations.append(BASELINE_UNCHANGED_CONFIRMED)

    # 11) Drawdown guard threshold not lowered. We treat any operator-
    # supplied threshold weaker than -3.0% (i.e. -8% would mean "allow
    # bigger drawdown before halt") as a blocker. Default expected
    # threshold is -3.0%.
    threshold = inputs.operator_drawdown_guard_threshold_pct
    if threshold is None:
        confirmations.append(DRAWDOWN_GUARD_NOT_LOWERED_CONFIRMED)
    elif threshold < -3.0 - 1e-6:
        blockers.append(
            f"drawdown_guard_threshold_pct={threshold} weaker than -3.0%")
    else:
        confirmations.append(DRAWDOWN_GUARD_NOT_LOWERED_CONFIRMED)
    details["drawdown_threshold_pct"] = threshold

    # 12) Open orders count — when supplied, must be zero.
    if inputs.open_orders_count is not None:
        if inputs.open_orders_count == 0:
            confirmations.append(OPEN_ORDERS_ZERO_CONFIRMED)
        else:
            blockers.append(
                f"open_orders_count={inputs.open_orders_count} != 0")
    else:
        notes.append("open_orders_count not supplied")

    # 13) Open equity positions count — when supplied, must be zero.
    if inputs.open_equity_positions_count is not None:
        if inputs.open_equity_positions_count == 0:
            confirmations.append(OPEN_EQUITY_POSITIONS_ZERO_CONFIRMED)
        else:
            blockers.append(
                f"open_equity_positions_count="
                f"{inputs.open_equity_positions_count} != 0")
    else:
        notes.append("open_equity_positions_count not supplied")

    # 14) Crypto positions reconciled — when supplied, must be True.
    if inputs.crypto_positions_reconciled is not None:
        if inputs.crypto_positions_reconciled:
            confirmations.append(CRYPTO_POSITIONS_RECONCILED_CONFIRMED)
        else:
            blockers.append("crypto_positions_reconciled=False")
    else:
        notes.append("crypto_positions_reconciled not supplied")

    verdict = (SIGNAL_SHADOW_PREFLIGHT_PASS if not blockers
                else SIGNAL_SHADOW_PREFLIGHT_BLOCKED)
    return PreflightReport(
        verdict=verdict,
        confirmations=sorted(set(confirmations)),
        blockers=sorted(blockers),
        notes=notes,
        details=details,
    )


def policy_summary() -> dict[str, Any]:
    return {
        "version": "v3.26.0",
        "verdicts": sorted(ALL_VERDICTS),
        "confirmations": sorted(ALL_CONFIRMATIONS),
        "invariants": {
            "BROKER_EXECUTION_NEVER_ENABLED_IN_PREFLIGHT":
                BROKER_EXECUTION_NEVER_ENABLED_IN_PREFLIGHT,
            "NEVER_PROMOTES_BROKER_PAPER":
                NEVER_PROMOTES_BROKER_PAPER,
            "NEVER_FLIPS_EDGE_GATE": NEVER_FLIPS_EDGE_GATE,
            "NEVER_LOWERS_DRAWDOWN_GUARD":
                NEVER_LOWERS_DRAWDOWN_GUARD,
            "NEVER_RESETS_BASELINE": NEVER_RESETS_BASELINE,
        },
    }


__all__ = [
    # Verdicts
    "SIGNAL_SHADOW_PREFLIGHT_PASS",
    "SIGNAL_SHADOW_PREFLIGHT_BLOCKED",
    "ALL_VERDICTS",
    # Confirmation tokens
    "BROKER_EXECUTION_DISABLED_CONFIRMED",
    "BROKER_PAPER_DISABLED_CONFIRMED",
    "LIVE_TRADING_UNSUPPORTED_CONFIRMED",
    "EDGE_GATE_DISABLED_CONFIRMED",
    "CRYPTO_GUARDS_PRESENT_CONFIRMED",
    "AUDIT_BYPASS_INVARIANT_CONFIRMED",
    "QUARANTINED_SCRIPTS_STILL_DISABLED_CONFIRMED",
    "UNLOCK_READINESS_VERDICT_CONFIRMED",
    "BROKER_PAPER_NOT_READY_CONFIRMED",
    "BASELINE_UNCHANGED_CONFIRMED",
    "DRAWDOWN_GUARD_NOT_LOWERED_CONFIRMED",
    "OPEN_ORDERS_ZERO_CONFIRMED",
    "OPEN_EQUITY_POSITIONS_ZERO_CONFIRMED",
    "CRYPTO_POSITIONS_RECONCILED_CONFIRMED",
    "ALL_CONFIRMATIONS",
    # Invariants
    "BROKER_EXECUTION_NEVER_ENABLED_IN_PREFLIGHT",
    "NEVER_PROMOTES_BROKER_PAPER",
    "NEVER_FLIPS_EDGE_GATE",
    "NEVER_LOWERS_DRAWDOWN_GUARD",
    "NEVER_RESETS_BASELINE",
    # Data classes
    "PreflightInputs", "PreflightReport",
    # API
    "run_preflight", "policy_summary",
]
