# LLM Advisory Activation Status (v3.28.2)

- **generated_at_iso:** `2026-06-16T12:17:28.921025+00:00`
- **gh_cli_available:** `True`
- **gh_cli_authenticated:** `False`
- **gemini_secret_present:** `False`
- **selected_provider:** `gemini`
- **llm_free_only:** `True`
- **variables_status:** `LLM_ACTIVATION_VARIABLES_FAILED`
- **schedule_enabled:** `False`
- **workflow_dispatch_status:** ``
- **latest_run_id:** `None`
- **latest_run_conclusion:** `None`
- **mesh_runner_status:** `None`
- **advisory_rows_emitted:** `0`
- **agents_attempted:** `0`
- **agents_completed:** `0`

## Blockers

- set-vars requires gh CLI authentication
- gh CLI not authenticated

## Standing markers

- `BROKER_PAPER_CANARY_STILL_BLOCKED`
- `LIVE_TRADING_UNSUPPORTED`
- `DETERMINISTIC_GATES_REMAIN_FINAL`
- `FREE_ONLY_POLICY_ENABLED`
- `PAID_PROVIDERS_BLOCKED_WHEN_FREE_ONLY`
- `OFFLINE_MOCK_STILL_DEFAULT`
- `API_KEYS_NOT_EXPOSED`
- `SCHEDULE_LEFT_DISABLED_BY_DEFAULT`

## Safety invariants

- `allow_broker_paper`: **false**
- `broker_execution_enabled`: **false**
- `broker_paper_canary_still_blocked`: **true**
- `deterministic_gates_remain_final`: **true**
- `edge_gate_enabled`: **false**
- `live_trading_unsupported`: **true**

## Next recommended action

- Run `gh auth login` and re-run this helper.
