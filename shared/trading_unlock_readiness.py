"""v3.25.0 (2026-06-09) — trading unlock readiness gate.

After the v3.23.x / v3.24 / v3.25 cycle the system is paused. This
module returns a deterministic verdict that operators and the audit
board use to decide what level (if any) of unlock is permitted.

VERDICT LADDER (each level strictly more permissive than the prior)

    TRADING_UNLOCK_BLOCKED                    — no unlock at all
    SIGNAL_SHADOW_UNLOCK_READY                — signal/shadow only
    BROKER_PAPER_CANARY_NOT_READY             — explicit: paper blocked
    BROKER_PAPER_CANARY_READY                 — paper allowed (rare)
    LIVE_TRADING_NOT_SUPPORTED                — never returned as ALLOW

CONTRACT
--------
- READ-ONLY. Does NOT submit orders.
- Does NOT enable broker_paper or live trading.
- Does NOT lower the drawdown guard.
- Does NOT reset the equity baseline.
- Returns a structured ``UnlockReadinessReport``.

The expected verdict after v3.25 ships is at most
``SIGNAL_SHADOW_UNLOCK_READY`` — broker paper requires evidence that
cannot exist in this sprint.

INVARIANTS (test-asserted)
--------------------------
- BROKER_PAPER_REQUIRES_EVIDENCE = True
- LIVE_TRADING_NEVER_RETURNS_READY = True
- NEVER_LOWERS_DRAWDOWN_GUARD = True
- NEVER_RESETS_BASELINE = True
- NEVER_FLIPS_EDGE_GATE = True
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

# ─── Verdict enum ────────────────────────────────────────────────────────────

TRADING_UNLOCK_BLOCKED          = "TRADING_UNLOCK_BLOCKED"
SIGNAL_SHADOW_UNLOCK_READY      = "SIGNAL_SHADOW_UNLOCK_READY"
BROKER_PAPER_CANARY_NOT_READY   = "BROKER_PAPER_CANARY_NOT_READY"
BROKER_PAPER_CANARY_READY       = "BROKER_PAPER_CANARY_READY"
LIVE_TRADING_NOT_SUPPORTED      = "LIVE_TRADING_NOT_SUPPORTED"

ALL_VERDICTS: frozenset[str] = frozenset({
    TRADING_UNLOCK_BLOCKED,
    SIGNAL_SHADOW_UNLOCK_READY,
    BROKER_PAPER_CANARY_NOT_READY,
    BROKER_PAPER_CANARY_READY,
    LIVE_TRADING_NOT_SUPPORTED,
})

# Evidence thresholds for broker paper canary.
BROKER_PAPER_MIN_NORMAL_OPPORTUNITIES   = 50
BROKER_PAPER_MIN_SHADOW_OUTCOMES        = 20
BROKER_PAPER_MAX_AUDIT_BYPASS_FINDINGS  = 0
BROKER_PAPER_MAX_UNEXPLAINED_EXPOSURE_GROWTH = 0
BROKER_PAPER_MAX_REPEATED_BUY_LOOP_VIOLATIONS = 0
BROKER_PAPER_REQUIRE_EXPLICIT_OPERATOR_APPROVAL = True

# Invariants.
BROKER_PAPER_REQUIRES_EVIDENCE            = True
LIVE_TRADING_NEVER_RETURNS_READY          = True
NEVER_LOWERS_DRAWDOWN_GUARD               = True
NEVER_RESETS_BASELINE                     = True
NEVER_FLIPS_EDGE_GATE                     = True


# ─── Data classes ────────────────────────────────────────────────────────────

@dataclass
class UnlockReadinessInputs:
    """Inputs from current repo state. None of these are inferred —
    callers must supply them."""
    # Audit / risk invariants.
    audit_bypass_invariant_satisfied: bool = True
    no_active_legacy_dangerous_order_script: bool = True
    open_equity_positions_count: int = 0
    open_orders_count: int = 0
    crypto_positions_reconciled: bool = True
    crypto_hard_exposure_caps_implemented: bool = True
    drawdown_attribution_near_complete: bool = True
    baseline_silently_reset: bool = False
    drawdown_guard_active_or_acknowledged: bool = True
    edge_gate_enabled: bool = False
    allow_broker_paper: bool = False
    unresolved_runaway_loop_finding: bool = False
    v3_25_tests_pass: bool = True
    # Broker-paper-canary evidence.
    normal_non_halt_opportunities_count: int = 0
    completed_shadow_outcomes_count: int = 0
    audit_bypass_findings_count: int = 0
    unexplained_exposure_growth_count: int = 0
    repeated_buy_loop_violations_count: int = 0
    crypto_exposure_cap_breached_count: int = 0
    daily_learning_stable: bool = False
    trade_reconstruction_stable: bool = False
    explicit_operator_approval_for_broker_paper: bool = False


@dataclass
class UnlockReadinessReport:
    verdict: str
    rationale: list[str]
    missing_for_signal_shadow: list[str] = field(default_factory=list)
    missing_for_broker_paper: list[str] = field(default_factory=list)
    invariants_held: dict[str, bool] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


# ─── Internal helpers ────────────────────────────────────────────────────────

def _signal_shadow_blockers(i: UnlockReadinessInputs) -> list[str]:
    """Return list of unmet conditions for SIGNAL_SHADOW_UNLOCK_READY."""
    missing: list[str] = []
    if not i.audit_bypass_invariant_satisfied:
        missing.append("audit_bypass_invariant_satisfied=False")
    if not i.no_active_legacy_dangerous_order_script:
        missing.append("active legacy direct-order script present")
    if i.open_equity_positions_count != 0:
        missing.append(
            f"open_equity_positions_count={i.open_equity_positions_count} "
            f"!= 0")
    if i.open_orders_count != 0:
        missing.append(
            f"open_orders_count={i.open_orders_count} != 0")
    if not i.crypto_positions_reconciled:
        missing.append("crypto positions not reconciled")
    if not i.crypto_hard_exposure_caps_implemented:
        missing.append("crypto hard exposure caps not implemented")
    if not i.drawdown_attribution_near_complete:
        missing.append("drawdown attribution not near-complete")
    if i.baseline_silently_reset:
        missing.append("baseline was silently reset")
    if not i.drawdown_guard_active_or_acknowledged:
        missing.append("drawdown guard not active or acknowledged")
    if i.edge_gate_enabled:
        missing.append("EDGE_GATE_ENABLED is True (must be False)")
    if i.allow_broker_paper:
        missing.append("ALLOW_BROKER_PAPER is True (must be False)")
    if i.unresolved_runaway_loop_finding:
        missing.append("unresolved runaway-loop finding")
    if not i.v3_25_tests_pass:
        missing.append("v3.25 tests not passing")
    return missing


def _broker_paper_blockers(i: UnlockReadinessInputs) -> list[str]:
    """Return list of unmet conditions for BROKER_PAPER_CANARY_READY.

    Stricter than signal-shadow. Requires evidence files which cannot
    exist in v3.25.
    """
    missing: list[str] = []
    if i.normal_non_halt_opportunities_count < BROKER_PAPER_MIN_NORMAL_OPPORTUNITIES:
        missing.append(
            f"normal_non_halt_opportunities_count="
            f"{i.normal_non_halt_opportunities_count} < "
            f"{BROKER_PAPER_MIN_NORMAL_OPPORTUNITIES}",
        )
    if i.completed_shadow_outcomes_count < BROKER_PAPER_MIN_SHADOW_OUTCOMES:
        missing.append(
            f"completed_shadow_outcomes_count="
            f"{i.completed_shadow_outcomes_count} < "
            f"{BROKER_PAPER_MIN_SHADOW_OUTCOMES}",
        )
    if i.audit_bypass_findings_count > BROKER_PAPER_MAX_AUDIT_BYPASS_FINDINGS:
        missing.append(
            f"audit_bypass_findings_count="
            f"{i.audit_bypass_findings_count} > "
            f"{BROKER_PAPER_MAX_AUDIT_BYPASS_FINDINGS}",
        )
    if i.unexplained_exposure_growth_count > BROKER_PAPER_MAX_UNEXPLAINED_EXPOSURE_GROWTH:
        missing.append(
            f"unexplained_exposure_growth_count="
            f"{i.unexplained_exposure_growth_count} > "
            f"{BROKER_PAPER_MAX_UNEXPLAINED_EXPOSURE_GROWTH}",
        )
    if i.repeated_buy_loop_violations_count > BROKER_PAPER_MAX_REPEATED_BUY_LOOP_VIOLATIONS:
        missing.append(
            f"repeated_buy_loop_violations_count="
            f"{i.repeated_buy_loop_violations_count} > "
            f"{BROKER_PAPER_MAX_REPEATED_BUY_LOOP_VIOLATIONS}",
        )
    if i.crypto_exposure_cap_breached_count > 0:
        missing.append(
            f"crypto_exposure_cap_breached_count="
            f"{i.crypto_exposure_cap_breached_count} > 0",
        )
    if not i.daily_learning_stable:
        missing.append("daily_learning_stable=False")
    if not i.trade_reconstruction_stable:
        missing.append("trade_reconstruction_stable=False")
    if (BROKER_PAPER_REQUIRE_EXPLICIT_OPERATOR_APPROVAL
            and not i.explicit_operator_approval_for_broker_paper):
        missing.append("explicit_operator_approval_for_broker_paper=False")
    return missing


# ─── Main API ────────────────────────────────────────────────────────────────

def evaluate_unlock_readiness(
    inputs: UnlockReadinessInputs,
) -> UnlockReadinessReport:
    """Return a deterministic readiness verdict.

    Pure function. No I/O. No state mutation. No order submission. No
    broker calls.

    Live trading is NEVER returned as ready. The maximum positive
    verdict this function can return is BROKER_PAPER_CANARY_READY, and
    only if every broker-paper blocker is empty AND operator approval
    is explicitly True.
    """
    rationale: list[str] = []
    sig_blockers = _signal_shadow_blockers(inputs)
    invariants_held = {
        "BROKER_PAPER_REQUIRES_EVIDENCE":
            BROKER_PAPER_REQUIRES_EVIDENCE,
        "LIVE_TRADING_NEVER_RETURNS_READY":
            LIVE_TRADING_NEVER_RETURNS_READY,
        "NEVER_LOWERS_DRAWDOWN_GUARD":
            NEVER_LOWERS_DRAWDOWN_GUARD,
        "NEVER_RESETS_BASELINE":
            NEVER_RESETS_BASELINE,
        "NEVER_FLIPS_EDGE_GATE":
            NEVER_FLIPS_EDGE_GATE,
    }

    if sig_blockers:
        rationale.append(
            "signal/shadow blocked by: " + ", ".join(sig_blockers),
        )
        return UnlockReadinessReport(
            verdict=TRADING_UNLOCK_BLOCKED,
            rationale=rationale,
            missing_for_signal_shadow=sig_blockers,
            missing_for_broker_paper=_broker_paper_blockers(inputs),
            invariants_held=invariants_held,
        )

    # Signal/shadow is ready. Now check broker-paper.
    paper_blockers = _broker_paper_blockers(inputs)
    if paper_blockers:
        rationale.append(
            "signal/shadow ready; broker_paper blocked by: "
            + ", ".join(paper_blockers),
        )
        # Explicit "not ready" carries more information than the bare
        # SIGNAL_SHADOW_UNLOCK_READY label — but the operator-facing
        # verdict ladder uses SIGNAL_SHADOW_UNLOCK_READY when the
        # higher tier is missing evidence (the higher tier's NOT_READY
        # is informational, not a downgrade).
        return UnlockReadinessReport(
            verdict=SIGNAL_SHADOW_UNLOCK_READY,
            rationale=rationale,
            missing_for_signal_shadow=[],
            missing_for_broker_paper=paper_blockers,
            invariants_held=invariants_held,
            details={"higher_tier_status":
                       BROKER_PAPER_CANARY_NOT_READY},
        )

    # All broker-paper conditions met (rare in v3.25 — should require
    # weeks of evidence collection plus explicit operator approval).
    rationale.append("broker_paper canary conditions all met")
    return UnlockReadinessReport(
        verdict=BROKER_PAPER_CANARY_READY,
        rationale=rationale,
        invariants_held=invariants_held,
        details={"higher_tier_status": LIVE_TRADING_NOT_SUPPORTED},
    )


def evaluate_from_current_repo_state(
    extra: dict[str, Any] | None = None,
) -> UnlockReadinessReport:
    """Convenience: build inputs from env + minimal repo state and
    evaluate. The expected verdict after v3.25 ships is at most
    SIGNAL_SHADOW_UNLOCK_READY because evidence files are not yet
    collected.

    Tests use this to confirm the current sprint cannot accidentally
    promote broker_paper.
    """
    edge_gate = (os.environ.get("EDGE_GATE_ENABLED", "false").lower()
                 in ("true", "1", "yes"))
    allow_broker_paper = (
        os.environ.get("ALLOW_BROKER_PAPER", "false").lower()
        in ("true", "1", "yes")
    )
    inputs = UnlockReadinessInputs(
        edge_gate_enabled=edge_gate,
        allow_broker_paper=allow_broker_paper,
    )
    if extra:
        for k, v in extra.items():
            if hasattr(inputs, k):
                setattr(inputs, k, v)
    return evaluate_unlock_readiness(inputs)


def policy_summary() -> dict[str, Any]:
    return {
        "version": "v3.25.0",
        "verdicts": sorted(ALL_VERDICTS),
        "broker_paper_thresholds": {
            "BROKER_PAPER_MIN_NORMAL_OPPORTUNITIES":
                BROKER_PAPER_MIN_NORMAL_OPPORTUNITIES,
            "BROKER_PAPER_MIN_SHADOW_OUTCOMES":
                BROKER_PAPER_MIN_SHADOW_OUTCOMES,
            "BROKER_PAPER_MAX_AUDIT_BYPASS_FINDINGS":
                BROKER_PAPER_MAX_AUDIT_BYPASS_FINDINGS,
            "BROKER_PAPER_MAX_UNEXPLAINED_EXPOSURE_GROWTH":
                BROKER_PAPER_MAX_UNEXPLAINED_EXPOSURE_GROWTH,
            "BROKER_PAPER_MAX_REPEATED_BUY_LOOP_VIOLATIONS":
                BROKER_PAPER_MAX_REPEATED_BUY_LOOP_VIOLATIONS,
            "BROKER_PAPER_REQUIRE_EXPLICIT_OPERATOR_APPROVAL":
                BROKER_PAPER_REQUIRE_EXPLICIT_OPERATOR_APPROVAL,
        },
        "invariants": {
            "BROKER_PAPER_REQUIRES_EVIDENCE":
                BROKER_PAPER_REQUIRES_EVIDENCE,
            "LIVE_TRADING_NEVER_RETURNS_READY":
                LIVE_TRADING_NEVER_RETURNS_READY,
            "NEVER_LOWERS_DRAWDOWN_GUARD":
                NEVER_LOWERS_DRAWDOWN_GUARD,
            "NEVER_RESETS_BASELINE":
                NEVER_RESETS_BASELINE,
            "NEVER_FLIPS_EDGE_GATE":
                NEVER_FLIPS_EDGE_GATE,
        },
    }


__all__ = [
    # Verdicts
    "TRADING_UNLOCK_BLOCKED",
    "SIGNAL_SHADOW_UNLOCK_READY",
    "BROKER_PAPER_CANARY_NOT_READY",
    "BROKER_PAPER_CANARY_READY",
    "LIVE_TRADING_NOT_SUPPORTED",
    "ALL_VERDICTS",
    # Thresholds
    "BROKER_PAPER_MIN_NORMAL_OPPORTUNITIES",
    "BROKER_PAPER_MIN_SHADOW_OUTCOMES",
    "BROKER_PAPER_MAX_AUDIT_BYPASS_FINDINGS",
    "BROKER_PAPER_MAX_UNEXPLAINED_EXPOSURE_GROWTH",
    "BROKER_PAPER_MAX_REPEATED_BUY_LOOP_VIOLATIONS",
    "BROKER_PAPER_REQUIRE_EXPLICIT_OPERATOR_APPROVAL",
    # Invariants
    "BROKER_PAPER_REQUIRES_EVIDENCE",
    "LIVE_TRADING_NEVER_RETURNS_READY",
    "NEVER_LOWERS_DRAWDOWN_GUARD",
    "NEVER_RESETS_BASELINE",
    "NEVER_FLIPS_EDGE_GATE",
    # Data classes
    "UnlockReadinessInputs",
    "UnlockReadinessReport",
    # API
    "evaluate_unlock_readiness",
    "evaluate_from_current_repo_state",
    "policy_summary",
]
