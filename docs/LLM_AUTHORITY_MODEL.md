# LLM Authority Model (v3.28 — 2026-06-09)

This document defines the **authority levels** that govern every LLM
advisory agent in the trading-system. The model is enforced
deterministically by [shared/llm_advisory_registry.py](../shared/llm_advisory_registry.py)
and asserted by `tests/test_llm_authority_model_v3280.py`.

## Why this exists

Before v3.28 the repository had per-monitor LLM curators (Reddit,
Politician, Crypto) and a learning-loop LLM client. Each one shipped
its own ad-hoc safety rules. v3.28 unifies the contract: every LLM
agent — present and future — carries an explicit `authority_level`
that bounds what it may do.

## Authority levels

| Level | Capability | Examples |
|---|---|---|
| `L0_OBSERVE_ONLY` | Read state only. Never produces a written recommendation. | Telemetry summariser, dashboard renderer. |
| `L1_EXPLAIN_ONLY` | Produces natural-language explanations of deterministic state, no recommendations. | "Why did the canary stay blocked today?" narrator. |
| `L2_RECOMMEND_ONLY` | May produce a recommendation field. Caller is free to ignore. | Signal-quality reviewer, no-signal diagnostic, market regime narrator. |
| `L3_VETO_RECOMMEND_ONLY` | May recommend that a deterministic gate downgrade or block. The deterministic gate still has the final say. | Pre-order advisory (recommends `VETO`), incident reviewer (recommends pause). |
| `L4_PROPOSE_CONFIG_CHANGE_ONLY` | May propose a structured risk/config change. The change goes through a normal PR + operator approval; LLM cannot apply it. | Risk-gate change proposal author. |
| `L5_EXECUTE_FORBIDDEN` | **Reserved. NEVER ASSIGNABLE.** Any code attempting to assign this level MUST fail. | n/a — sentinel. |

## Default ceilings

- All advisory agents default to **at most `L3_VETO_RECOMMEND_ONLY`**.
- The risk-gate change proposal agent is the only agent permitted
  `L4_PROPOSE_CONFIG_CHANGE_ONLY`.
- `L5_EXECUTE_FORBIDDEN` is a sentinel value used to verify "no LLM
  can execute" — assigning it is a programming error and raises
  `ValueError`.

## Hard rules (enforced by deterministic code)

1. **LLM cannot execute.** No advisory module may import
   `shared/alpaca_orders.py` or call `submit_order` / `place_order` /
   `safe_close`. Asserted by `tests/test_llm_no_execution_control_v3280.py`.
2. **LLM cannot force a trade.** `L3_VETO_RECOMMEND_ONLY` agents may
   recommend a veto, but the deterministic risk_officer / portfolio_risk
   gate decides whether to honour it.
3. **LLM cannot force a risk change.** `L4_PROPOSE_CONFIG_CHANGE_ONLY`
   proposals always set `auto_apply: false` and
   `requires_operator_approval: true`.
4. **LLM cannot unlock broker paper.** Setting
   `ALLOW_BROKER_PAPER` / `EDGE_GATE_ENABLED` /
   `BROKER_EXECUTION_ENABLED` from advisory output is impossible —
   the modules don't read or write those flags.
5. **LLM cannot enable live trading.** No advisory output ever causes
   `LIVE_TRADING` / `LIVE_ENABLED` / `GO_LIVE` /
   `LIVE_TRADING_ENABLED` to flip.
6. **LLM cannot change readiness verdicts.** The trading_unlock_readiness
   gate consumes only deterministic counters. Advisory output is
   filtered out of the counter pipeline (`affects_readiness_gate: false`
   is pinned in the advisory schema enum).
7. **LLM advisory output is evidence, not execution authority.** Every
   advisory row carries `advisory_only: true`, `may_execute: false`,
   `may_modify_risk: false`, `may_unlock_broker_paper: false`,
   `broker_order_submitted: false`, `broker_execution_enabled: false`,
   `affects_readiness_gate: false`. These are JSON Schema enums, so
   any output that violates them fails validation and never reaches
   disk.

## Process stages and default authority

| Stage | Default authority | Notes |
|---|---|---|
| `MARKET_REGIME` | `L2_RECOMMEND_ONLY` | Narrate today's macro regime. |
| `SIGNAL_REVIEW` | `L2_RECOMMEND_ONLY` | Comment on signal quality. |
| `NO_SIGNAL_DIAGNOSTIC` | `L2_RECOMMEND_ONLY` | Explain `REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL`. |
| `SHADOW_OPPORTUNITY_REVIEW` | `L2_RECOMMEND_ONLY` | Critique the day's shadow records. |
| `SHADOW_OUTCOME_REVIEW` | `L2_RECOMMEND_ONLY` | Critique the day's resolved outcomes. |
| `PRE_ORDER_ADVISORY` | `L3_VETO_RECOMMEND_ONLY` | Recommend WARN / VETO before an order is constructed. The deterministic risk_officer makes the final call. |
| `RISK_NARRATIVE_REVIEW` | `L2_RECOMMEND_ONLY` | Narrate today's risk posture. |
| `RISK_GATE_CHANGE_PROPOSAL` | `L4_PROPOSE_CONFIG_CHANGE_ONLY` | The only L4 agent. `auto_apply: false`. |
| `INCIDENT_REVIEW` | `L3_VETO_RECOMMEND_ONLY` | May recommend pausing a strategy. |
| `BROKER_PAPER_CANARY_REVIEW` | `L2_RECOMMEND_ONLY` | Reviews readiness counters but cannot flip the verdict. |
| `FINAL_ADVISORY_ARBITER` | `L3_VETO_RECOMMEND_ONLY` | Cross-agent synthesis. Same authority ceiling as the agents it summarises. |

## Status tokens (added in v3.28)

- `LLM_CLOUD_ADVISORY_MESH_ADDED`
- `LLM_AUTHORITY_MODEL_ADDED`
- `LLM_ORDER_EXECUTION_DIRECT_CONTROL_FORBIDDEN`
- `LLM_RISK_GATE_DIRECT_MUTATION_FORBIDDEN`
- `LLM_VETO_RECOMMEND_ONLY`
- `LLM_RISK_CHANGE_PROPOSAL_ONLY`
- `DETERMINISTIC_GATES_REMAIN_FINAL`
- `LLM_OUTPUT_NEVER_COUNTS_AS_REAL_MARKET_EVIDENCE`

## Implementation references

- [shared/llm_advisory_registry.py](../shared/llm_advisory_registry.py) — `ALL_AUTHORITY_LEVELS`, `ALL_PROCESS_STAGES`, agent definitions.
- [shared/llm_agent_budget.py](../shared/llm_agent_budget.py) — daily / per-run / cost caps, default `LLM_AGENTS_ENABLED=false`.
- [shared/llm_provider_client.py](../shared/llm_provider_client.py) — offline-mock by default; provider call is short-circuited when disabled.
- [shared/llm_pre_order_advisory.py](../shared/llm_pre_order_advisory.py) — returns one of `ADVISORY_PASS` / `ADVISORY_WARN` / `ADVISORY_VETO_RECOMMENDED` / `ADVISORY_SKIPPED_*` / `ADVISORY_ERROR_FAIL_SOFT` — never `EXECUTE`.
- [shared/llm_risk_change_proposal.py](../shared/llm_risk_change_proposal.py) — proposals always carry `auto_apply: false`.
- [learning-loop/llm_advisory/schema.json](../learning-loop/llm_advisory/schema.json) — JSON Schema with pinned enums for every safety-critical field.
- [scripts/run_llm_advisory_mesh.py](../scripts/run_llm_advisory_mesh.py) — cloud-callable runner.
- [.github/workflows/llm-advisory-mesh.yml](../.github/workflows/llm-advisory-mesh.yml) — disabled-by-default workflow.


---

## v3.29 ETAP 6 — strict advisory schema

The v3.29 mesh runs every advisory call through
[`shared/llm_advisory_authority.py`](../shared/llm_advisory_authority.py)
which defines the canonical `LLMAdvisoryOutput` dataclass.

**Schema invariants (enforced in `__post_init__`):**
- `advisory_only = True`
- `must_not_execute_orders = True`
- `authority_level ∈ {L0_ADVISORY_ONLY, L1_VETO_RECOMMEND_ONLY}`
- `agent_name ∈ ADVISORY_ROLES` (10 roles)
- No FORBIDDEN_OUTPUTS token in any string field

**Forbidden output tokens:**
- `CLEAR_SAFE_MODE`
- `EXECUTE_ORDER`
- `FLIP_BROKER_FLAG`
- `MUTATE_THRESHOLD`
- `OVERRIDE_GATE`
- `PLACE_ORDER`
- `PROMOTE_VARIANT`

**Advisory roles (10):**
- `ALLOCATOR_PLAN_CRITIC`
- `DAILY_BRIEF`
- `EQUITY_RECONCILIATION_CRITIC`
- `FINAL_ARBITER`
- `INCIDENT_REVIEW`
- `NO_SIGNAL_DIAGNOSTIC`
- `RISK_REVIEW`
- `SHADOW_CANDIDATE_REVIEW`
- `STRATEGY_REVIEW`
- `TRIGGER_WATCHLIST_REVIEW`

**Standing markers asserted on every persistence:**
- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE`
- `NO_LLM_STATE_MUTATION`
- `DETERMINISTIC_GATES_REMAIN_FINAL`
- `LLM_PRE_ORDER_VETO_REMAINS_DISABLED`
- `SCHEDULE_REMAINS_DISABLED_BY_DEFAULT`
