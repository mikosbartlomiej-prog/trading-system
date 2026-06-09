# Broker-Paper Canary Unlock Status (v3.30)

- **Unlock status:** `BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY_SOURCE_MISMATCH`
- **Stage:** `STAGE_0_SHADOW_ONLY`

## Gates


## Rationale

- quality_history.jsonl missing run_id=v3283-mock-3; latest snapshot may be stale

## Safety invariants

- `allow_broker_paper`: **false**
- `broker_execution_enabled`: **false**
- `broker_paper_canary_still_blocked`: **true**
- `deterministic_gates_remain_final`: **true**
- `edge_gate_enabled`: **false**
- `live_trading_unsupported`: **true**
- `llm_pre_order_veto_honored`: **false**
- `schedule_enabled`: **false**

## Standing markers

- `LLM_STRATEGY_ALIGNMENT_ENFORCED`
- `LLM_ADVISORY_ONLY_CONFIRMED`
- `DETERMINISTIC_GATES_REMAIN_FINAL`
- `LLM_OUTPUT_DOES_NOT_COUNT_AS_REAL_MARKET_EVIDENCE`
- `BROKER_PAPER_CANARY_ONLY_NOT_BROAD_TRADING`
- `LIVE_TRADING_UNSUPPORTED`
- `SCHEDULE_REMAINS_DISABLED_UNTIL_REPEATED_ACCEPTABLE_QUALITY`
- `LLM_PRE_ORDER_VETO_REMAINS_DISABLED`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `CANARY_PRE_EXECUTOR_PREFLIGHT_ONLY`
- `NO_ORDER_PLACEMENT_IN_V330`
