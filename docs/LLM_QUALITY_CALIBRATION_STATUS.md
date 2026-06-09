# LLM Quality Calibration Status (v3.30)

- **Precheck status:** `CALIBRATION_SKIPPED_DISABLED`
- **Calibration enabled:** false
- **Accepted quality runs:** 0
- **Budget status:** `LLM_BUDGET_DISABLED`
- **Provider:** `offline_mock`
- **Model:** ``
- **Next action:** Set LLM_QUALITY_CALIBRATION_ENABLED=true (repo variable) to opt in.

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

- `LLM_ADVISORY_ONLY_CONFIRMED`
- `CALIBRATION_SCHEDULE_BOUNDED`
- `PRODUCTION_LLM_SCHEDULE_REMAINS_DISABLED`
- `LLM_PRE_ORDER_VETO_REMAINS_DISABLED`
- `BROKER_PAPER_CANARY_ONLY_NOT_BROAD_TRADING`
- `LIVE_TRADING_UNSUPPORTED`
- `DETERMINISTIC_GATES_REMAIN_FINAL`
