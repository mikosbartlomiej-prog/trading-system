# LLM Advisory Mesh — latest run (v3.28.3)

- **Run ID:** `v329-gemini-recovery-postreqs-20260609T203552Z`
- **Status:** `LLM_ADVISORY_MESH_RAN`
- **Quality status:** `LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER`
- **Selected provider:** `gemini`
- **LLM_FREE_ONLY:** `True`
- **Agents evaluated:** 4
- **Rows written:** 4
- **Standing markers:** `BROKER_PAPER_CANARY_STILL_BLOCKED`, `LIVE_TRADING_UNSUPPORTED`

## Quality report (v3.28.3)

- rows_with_provider_used: **4**
- rows_with_provider_skipped: 0
- rows_with_provider_failed: 0
- generic_placeholder_count: 0
- empty_risks_count: 4
- empty_next_actions_count: 4
- confidence range: [0.0, 0.0]
- secret_leak_hits: 0
- unsafe_phrase_hits: 0

**Next recommended action:** Improve per-agent prompts so Gemini emits concrete evidence-grounded analysis. Do NOT enable schedule.

## Safety invariants (asserted on every run)
- `broker_paper_canary_still_blocked`: **true**
- `live_trading_unsupported`: **true**
- LLM agents NEVER submit orders.
- LLM agents NEVER import the broker-orders module.
- LLM agents NEVER mutate readiness counters.
- LLM agents NEVER mutate risk config.
- Deterministic gates remain final.

