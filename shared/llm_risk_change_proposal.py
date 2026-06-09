"""v3.28 (2026-06-09) — LLM risk-gate change proposal module.

Produces STRUCTURED PROPOSALS only. Hard rules:

- ``auto_apply`` is ALWAYS ``false``.
- ``requires_operator_approval`` is ALWAYS ``true``.
- ``advisory_only`` is ALWAYS ``true``.
- No risk config file may be modified by this module.
- Proposal output does not change the readiness gate.
- NEVER imports the broker-orders module.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class RiskChangeProposal:
    proposal_id:                  str
    agent_name:                   str
    current_config_ref:           str
    proposed_change:              dict
    rationale:                    str
    expected_effect:              str
    safety_constraints:           list[str] = field(default_factory=list)
    requires_tests:               bool = True
    requires_operator_approval:   bool = True
    auto_apply:                   bool = False
    advisory_only:                bool = True

    def __post_init__(self):
        if self.auto_apply is not False:
            raise ValueError(
                "auto_apply MUST be False on every risk change proposal")
        if self.requires_operator_approval is not True:
            raise ValueError(
                "requires_operator_approval MUST be True")
        if self.advisory_only is not True:
            raise ValueError("advisory_only MUST be True")
        # Safety constraints must list the forbidden actions confirmed.
        required = {
            "ORDER_EXECUTION", "POSITION_MODIFICATION",
            "RISK_GATE_DIRECT_MUTATION", "BROKER_PAPER_UNLOCK",
            "LIVE_TRADING_ENABLEMENT", "BASELINE_RESET",
            "DRAWDOWN_GUARD_LOWERING", "READINESS_COUNTER_MUTATION",
        }
        if not required.issubset(set(self.safety_constraints)):
            # Auto-attach to keep callers honest.
            self.safety_constraints = sorted(
                set(self.safety_constraints) | required)

    def to_dict(self) -> dict:
        return {
            "proposal_id":                self.proposal_id,
            "agent_name":                 self.agent_name,
            "current_config_ref":         self.current_config_ref,
            "proposed_change":            self.proposed_change,
            "rationale":                  self.rationale,
            "expected_effect":            self.expected_effect,
            "safety_constraints":         sorted(self.safety_constraints),
            "requires_tests":             True,
            "requires_operator_approval": True,
            "auto_apply":                 False,
            "advisory_only":              True,
        }


def build_proposal(
    *,
    current_config_ref: str,
    proposed_change: dict,
    rationale: str,
    expected_effect: str,
    agent_name: str = "RISK_GATE_CHANGE_PROPOSAL_AGENT",
) -> RiskChangeProposal:
    """Pure constructor — does NOT touch disk or env. Returns a
    proposal with the hard-coded safety invariants.
    """
    proposal_id = f"rcp-{uuid.uuid4().hex[:12]}"
    return RiskChangeProposal(
        proposal_id=proposal_id,
        agent_name=agent_name,
        current_config_ref=current_config_ref,
        proposed_change=dict(proposed_change or {}),
        rationale=rationale,
        expected_effect=expected_effect,
    )


def applies_to_risk_config(proposal: RiskChangeProposal) -> bool:
    """Returns False. This module CANNOT apply risk config changes.

    Provided so callers can write::

        if applies_to_risk_config(proposal):
            actually_change_config()

    and the static answer ``False`` makes the dead branch obvious.
    """
    # Hard-coded: this module never applies anything.
    _ = proposal  # silence linters
    return False


def assert_proposal_is_safe(proposal: RiskChangeProposal) -> None:
    """Re-assert the invariants. Raises ``ValueError`` if any are
    violated."""
    if proposal.auto_apply is not False:
        raise ValueError("auto_apply must be False")
    if proposal.requires_operator_approval is not True:
        raise ValueError("requires_operator_approval must be True")
    if proposal.advisory_only is not True:
        raise ValueError("advisory_only must be True")


__all__ = [
    "RiskChangeProposal", "build_proposal",
    "applies_to_risk_config", "assert_proposal_is_safe",
]
