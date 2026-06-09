# LLM Advisory Mesh — latest run (v3.28.3)

- **Run ID:** `v3291-gemini-quality-a-20260609T210119Z`
- **Status:** `LLM_ADVISORY_MESH_SKIPPED_BUDGET`
- **Quality status:** `LLM_ADVISORY_QUALITY_INSUFFICIENT_SAMPLE`
- **Selected provider:** `gemini`
- **LLM_FREE_ONLY:** `True`
- **Agents evaluated:** 0
- **Rows written:** 0
- **Standing markers:** `BROKER_PAPER_CANARY_STILL_BLOCKED`, `LIVE_TRADING_UNSUPPORTED`

## Quality report (v3.28.3)

- rows_with_provider_used: **0**
- rows_with_provider_skipped: 0
- rows_with_provider_failed: 0
- generic_placeholder_count: 0
- empty_risks_count: 0
- empty_next_actions_count: 0
- confidence range: [1.0, 0.0]
- secret_leak_hits: 0
- unsafe_phrase_hits: 0

## Safety invariants (asserted on every run)
- `broker_paper_canary_still_blocked`: **true**
- `live_trading_unsupported`: **true**
- LLM agents NEVER submit orders.
- LLM agents NEVER import the broker-orders module.
- LLM agents NEVER mutate readiness counters.
- LLM agents NEVER mutate risk config.
- Deterministic gates remain final.

