"""v3.28 (2026-06-09) — LLM advisory agent registry.

Canonical definition of every LLM advisory agent in the trading
system. Each agent carries an explicit ``authority_level`` (see
[docs/LLM_AUTHORITY_MODEL.md](../docs/LLM_AUTHORITY_MODEL.md)) and a
``forbidden_actions`` list that is asserted at runtime.

HARD SAFETY
-----------
- NEVER imports the broker-orders module.
- ``L5_EXECUTE_FORBIDDEN`` is a sentinel: assigning it raises
  ``ValueError``.
- Every agent's ``forbidden_actions`` list includes ALL ten
  forbidden capability tokens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ─── Authority levels ──────────────────────────────────────────────────────

L0_OBSERVE_ONLY                = "L0_OBSERVE_ONLY"
L1_EXPLAIN_ONLY                = "L1_EXPLAIN_ONLY"
L2_RECOMMEND_ONLY              = "L2_RECOMMEND_ONLY"
L3_VETO_RECOMMEND_ONLY         = "L3_VETO_RECOMMEND_ONLY"
L4_PROPOSE_CONFIG_CHANGE_ONLY  = "L4_PROPOSE_CONFIG_CHANGE_ONLY"
# Sentinel — NEVER ASSIGNABLE.
L5_EXECUTE_FORBIDDEN           = "L5_EXECUTE_FORBIDDEN"

ALL_AUTHORITY_LEVELS: frozenset[str] = frozenset({
    L0_OBSERVE_ONLY, L1_EXPLAIN_ONLY,
    L2_RECOMMEND_ONLY, L3_VETO_RECOMMEND_ONLY,
    L4_PROPOSE_CONFIG_CHANGE_ONLY,
})

# Levels permitted on serialized output (L5 sentinel never appears).
ASSIGNABLE_LEVELS: frozenset[str] = frozenset(ALL_AUTHORITY_LEVELS)


# ─── Process stages ────────────────────────────────────────────────────────

MARKET_REGIME                = "MARKET_REGIME"
SIGNAL_REVIEW                = "SIGNAL_REVIEW"
NO_SIGNAL_DIAGNOSTIC         = "NO_SIGNAL_DIAGNOSTIC"
SHADOW_OPPORTUNITY_REVIEW    = "SHADOW_OPPORTUNITY_REVIEW"
SHADOW_OUTCOME_REVIEW        = "SHADOW_OUTCOME_REVIEW"
PRE_ORDER_ADVISORY           = "PRE_ORDER_ADVISORY"
RISK_NARRATIVE_REVIEW        = "RISK_NARRATIVE_REVIEW"
RISK_GATE_CHANGE_PROPOSAL    = "RISK_GATE_CHANGE_PROPOSAL"
INCIDENT_REVIEW              = "INCIDENT_REVIEW"
BROKER_PAPER_CANARY_REVIEW   = "BROKER_PAPER_CANARY_REVIEW"
FINAL_ADVISORY_ARBITER       = "FINAL_ADVISORY_ARBITER"

ALL_PROCESS_STAGES: frozenset[str] = frozenset({
    MARKET_REGIME, SIGNAL_REVIEW, NO_SIGNAL_DIAGNOSTIC,
    SHADOW_OPPORTUNITY_REVIEW, SHADOW_OUTCOME_REVIEW,
    PRE_ORDER_ADVISORY, RISK_NARRATIVE_REVIEW,
    RISK_GATE_CHANGE_PROPOSAL, INCIDENT_REVIEW,
    BROKER_PAPER_CANARY_REVIEW, FINAL_ADVISORY_ARBITER,
})


# ─── Forbidden capability tokens ───────────────────────────────────────────

FORBIDDEN_ACTIONS: tuple[str, ...] = (
    "ORDER_EXECUTION",
    "POSITION_MODIFICATION",
    "RISK_GATE_DIRECT_MUTATION",
    "BROKER_PAPER_UNLOCK",
    "LIVE_TRADING_ENABLEMENT",
    "BASELINE_RESET",
    "DRAWDOWN_GUARD_LOWERING",
    "READINESS_COUNTER_MUTATION",
    "MARKET_DATA_FABRICATION",
    "PNL_FABRICATION",
)


# ─── Agent definition ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class AgentDefinition:
    name:              str
    process_stage:     str
    authority_level:   str
    allowed_inputs:    tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    output_schema:     str
    max_calls_per_run: int
    fail_soft_behavior: str
    prompt_template:   str

    def __post_init__(self):
        if self.authority_level == L5_EXECUTE_FORBIDDEN:
            raise ValueError(
                f"L5_EXECUTE_FORBIDDEN is a sentinel and CANNOT be "
                f"assigned to an agent (attempted on {self.name})")
        if self.authority_level not in ASSIGNABLE_LEVELS:
            raise ValueError(
                f"unknown authority_level={self.authority_level!r} "
                f"on {self.name}")
        if self.process_stage not in ALL_PROCESS_STAGES:
            raise ValueError(
                f"unknown process_stage={self.process_stage!r} "
                f"on {self.name}")
        # Every agent must confirm all 10 forbidden actions.
        missing = set(FORBIDDEN_ACTIONS) - set(self.forbidden_actions)
        if missing:
            raise ValueError(
                f"agent {self.name} forbidden_actions missing: "
                f"{sorted(missing)}")


def _agent(*, name, stage, level, max_calls, inputs):
    return AgentDefinition(
        name=name,
        process_stage=stage,
        authority_level=level,
        allowed_inputs=inputs,
        forbidden_actions=FORBIDDEN_ACTIONS,
        output_schema="learning-loop/llm_advisory/schema.json",
        max_calls_per_run=max_calls,
        fail_soft_behavior=(
            "On any error, emit an advisory row with "
            "recommendation='skipped' and confidence=0.0 — never raise."
        ),
        prompt_template=(
            f"You are {name}. You are an ADVISORY agent. You CANNOT "
            f"execute, modify positions, change risk config, unlock "
            f"broker paper, enable live trading, lower the drawdown "
            f"guard, reset the baseline, mutate readiness counters, "
            f"or fabricate market data / P&L. You MAY observe, "
            f"explain, recommend, recommend a veto, or propose a "
            f"config change as a structured proposal. "
            f"Authority level: {level}. Process stage: {stage}."
        ),
    )


REGISTRY: dict[str, AgentDefinition] = {
    "MARKET_REGIME_AGENT": _agent(
        name="MARKET_REGIME_AGENT",
        stage=MARKET_REGIME, level=L2_RECOMMEND_ONLY, max_calls=1,
        inputs=("evidence_counters_latest.json",
                 "workflow_health_latest.json"),
    ),
    "SIGNAL_QUALITY_AGENT": _agent(
        name="SIGNAL_QUALITY_AGENT",
        stage=SIGNAL_REVIEW, level=L2_RECOMMEND_ONLY, max_calls=1,
        inputs=("records_latest.jsonl",),
    ),
    "DATA_QUALITY_AGENT": _agent(
        name="DATA_QUALITY_AGENT",
        stage=NO_SIGNAL_DIAGNOSTIC, level=L2_RECOMMEND_ONLY, max_calls=1,
        inputs=("workflow_health_latest.json",
                 "workflow_health_history.jsonl"),
    ),
    "NO_SIGNAL_DIAGNOSTIC_AGENT": _agent(
        name="NO_SIGNAL_DIAGNOSTIC_AGENT",
        stage=NO_SIGNAL_DIAGNOSTIC, level=L2_RECOMMEND_ONLY, max_calls=1,
        inputs=("workflow_health_history.jsonl",
                 "first_real_market_record_status.json"),
    ),
    "SHADOW_OUTCOME_REVIEW_AGENT": _agent(
        name="SHADOW_OUTCOME_REVIEW_AGENT",
        stage=SHADOW_OUTCOME_REVIEW, level=L2_RECOMMEND_ONLY,
        max_calls=1, inputs=("outcomes_latest.jsonl",),
    ),
    "PRE_ORDER_ADVISORY_AGENT": _agent(
        name="PRE_ORDER_ADVISORY_AGENT",
        stage=PRE_ORDER_ADVISORY, level=L3_VETO_RECOMMEND_ONLY,
        max_calls=1, inputs=("draft_order_context",),
    ),
    "RISK_NARRATIVE_AGENT": _agent(
        name="RISK_NARRATIVE_AGENT",
        stage=RISK_NARRATIVE_REVIEW, level=L2_RECOMMEND_ONLY,
        max_calls=1,
        inputs=("evidence_counters_latest.json",
                 "trading_unlock_readiness_latest.json"),
    ),
    "RISK_GATE_CHANGE_PROPOSAL_AGENT": _agent(
        name="RISK_GATE_CHANGE_PROPOSAL_AGENT",
        stage=RISK_GATE_CHANGE_PROPOSAL,
        level=L4_PROPOSE_CONFIG_CHANGE_ONLY,
        max_calls=1, inputs=("risk_config_snapshot",),
    ),
    "INCIDENT_REVIEW_AGENT": _agent(
        name="INCIDENT_REVIEW_AGENT",
        stage=INCIDENT_REVIEW, level=L3_VETO_RECOMMEND_ONLY,
        max_calls=1, inputs=("recent_incidents",),
    ),
    "BROKER_PAPER_CANARY_REVIEW_AGENT": _agent(
        name="BROKER_PAPER_CANARY_REVIEW_AGENT",
        stage=BROKER_PAPER_CANARY_REVIEW, level=L2_RECOMMEND_ONLY,
        max_calls=1,
        inputs=("trading_unlock_readiness_latest.json",
                 "evidence_counters_latest.json"),
    ),
    "FINAL_ADVISORY_ARBITER": _agent(
        name="FINAL_ADVISORY_ARBITER",
        stage=FINAL_ADVISORY_ARBITER, level=L3_VETO_RECOMMEND_ONLY,
        max_calls=1, inputs=("all_prior_agent_outputs",),
    ),
}


def all_agents() -> tuple[AgentDefinition, ...]:
    return tuple(REGISTRY.values())


def agent_for(name: str) -> AgentDefinition:
    if name not in REGISTRY:
        raise KeyError(f"unknown agent: {name!r}")
    return REGISTRY[name]


def assert_assignable_authority(level: str) -> None:
    """Raise if ``level`` is not assignable (covers L5 sentinel)."""
    if level == L5_EXECUTE_FORBIDDEN:
        raise ValueError(
            "L5_EXECUTE_FORBIDDEN is a sentinel and CANNOT be "
            "assigned to an agent or to advisory output")
    if level not in ASSIGNABLE_LEVELS:
        raise ValueError(f"unknown authority_level={level!r}")


__all__ = [
    # Authority levels
    "L0_OBSERVE_ONLY", "L1_EXPLAIN_ONLY",
    "L2_RECOMMEND_ONLY", "L3_VETO_RECOMMEND_ONLY",
    "L4_PROPOSE_CONFIG_CHANGE_ONLY", "L5_EXECUTE_FORBIDDEN",
    "ALL_AUTHORITY_LEVELS", "ASSIGNABLE_LEVELS",
    # Process stages
    "MARKET_REGIME", "SIGNAL_REVIEW", "NO_SIGNAL_DIAGNOSTIC",
    "SHADOW_OPPORTUNITY_REVIEW", "SHADOW_OUTCOME_REVIEW",
    "PRE_ORDER_ADVISORY", "RISK_NARRATIVE_REVIEW",
    "RISK_GATE_CHANGE_PROPOSAL", "INCIDENT_REVIEW",
    "BROKER_PAPER_CANARY_REVIEW", "FINAL_ADVISORY_ARBITER",
    "ALL_PROCESS_STAGES",
    # Forbidden actions
    "FORBIDDEN_ACTIONS",
    # Registry
    "AgentDefinition", "REGISTRY", "all_agents", "agent_for",
    "assert_assignable_authority",
]
