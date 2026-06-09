# LLM Advisory Quality Review (v3.28.3)

- **Run ID:** `v329-gemini-recovery-postreqs-20260609T203552Z`
- **Quality status:** `LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER`
- **Rows seen:** 4
- **Rows with PROVIDER_USED:** **4**
- **Rows with PROVIDER_SKIPPED_DISABLED:** 0
- **Rows with PROVIDER_FAILED_FAIL_SOFT:** 0
- **generic_placeholder_count:** 0
- **empty_risks_count:** 4
- **empty_next_actions_count:** 4
- **zero_confidence_count:** 4
- **secret_leak_hits:** 0
- **unsafe_phrase_hits:** 0

## Rationale

- 0/4 rows look like generic placeholder; empty-risks=4; empty-next=4; zero-conf=4

## Safety invariants

- `allow_broker_paper`: **false**
- `broker_execution_enabled`: **false**
- `broker_paper_canary_still_blocked`: **true**
- `edge_gate_enabled`: **false**
- `live_trading_unsupported`: **true**
- `llm_pre_order_veto_honored`: **false**
- `schedule_enabled`: **false**
