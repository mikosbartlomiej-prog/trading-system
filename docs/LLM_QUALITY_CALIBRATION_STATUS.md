# LLM Quality Calibration Status (v3.30.1)

- **Precheck status:** `CALIBRATION_PROCEEDING`
- **Should call provider:** true
- **Accepted quality runs:** 0 / 2
- **Budget status:** `LLM_BUDGET_ALLOWED`
- **Provider:** `gemini`
- **Free-only:** true
- **Production LLM schedule enabled:** false
- **Broker flags safe:** true
- **Gemini key present:** true
- **Calibration disabled by operator:** false
- **Latest quality status:** `LLM_ADVISORY_QUALITY_EMPTY_ANALYSIS`
- **Latest run_id:** `v3300-calibration-28840937021`
- **Next action:** Proceed to Gemini smoke + bounded mesh run with per-run budget override = 11.

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
