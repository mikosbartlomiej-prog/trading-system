# LLM Quality History Repair Status (v3.30.1)

- **Repair status:** `QUALITY_HISTORY_ALREADY_CONSISTENT`
- **Latest run_id:** `v3283-mock-3`
- **Anti-mock passed:** false
- **Source mismatch:** false
- **Stale snapshot:** false
- **Mock-pattern run_id:** true
- **Accepted for unlock counting:** false

## Rationale

- run_id=v3283-mock-3 already in history; anti_mock_passed=False; accepted_for_unlock_counting=False

## Safety invariants

- `allow_broker_paper`: **false**
- `broker_execution_enabled`: **false**
- `broker_paper_canary_still_blocked`: **true**
- `deterministic_gates_remain_final`: **true**
- `edge_gate_enabled`: **false**
- `live_trading_unsupported`: **true**
- `llm_pre_order_veto_honored`: **false**
- `no_order_placement_in_v3301`: **true**
- `schedule_enabled`: **false**

## Standing markers

- `NO_MANUAL_REPO_VARIABLE_REQUIRED_FOR_CALIBRATION`
- `STALE_MOCK_QUALITY_NEVER_COUNTS_AS_ACCEPTABLE`
- `CALIBRATION_BOUNDED_FREE_ONLY_GEMINI`
- `PRODUCTION_LLM_SCHEDULE_REMAINS_DISABLED`
- `LLM_PRE_ORDER_VETO_REMAINS_DISABLED`
- `CANARY_PRE_EXECUTOR_PREFLIGHT_ONLY`
- `NO_ORDER_PLACEMENT`
- `BROKER_PAPER_CANARY_ONLY_NOT_BROAD_TRADING`
- `LIVE_TRADING_UNSUPPORTED`
- `DETERMINISTIC_GATES_REMAIN_FINAL`
