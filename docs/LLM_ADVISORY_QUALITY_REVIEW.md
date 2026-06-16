# LLM Advisory Quality Review (v3.28.3)

- **Run ID:** `v3283-mock-3`
- **Quality status:** `LLM_ADVISORY_QUALITY_ACCEPTABLE`
- **Rows seen:** 5
- **Rows with PROVIDER_USED:** **5**
- **Rows with PROVIDER_SKIPPED_DISABLED:** 0
- **Rows with PROVIDER_FAILED_FAIL_SOFT:** 0
- **generic_placeholder_count:** 0
- **empty_risks_count:** 0
- **empty_next_actions_count:** 0
- **zero_confidence_count:** 0
- **secret_leak_hits:** 0
- **unsafe_phrase_hits:** 0

## Rationale

- acceptable

## Safety invariants

- `allow_broker_paper`: **false**
- `broker_execution_enabled`: **false**
- `broker_paper_canary_still_blocked`: **true**
- `edge_gate_enabled`: **false**
- `live_trading_unsupported`: **true**
- `llm_pre_order_veto_honored`: **false**
- `schedule_enabled`: **false**
