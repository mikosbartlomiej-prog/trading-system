# LLM Advisory Mesh — v3.29 ETAP 6 status

- **Generated at:** 2026-06-16T09:21:27.565441+00:00
- **Status:** `V329_MESH_DRY_RUN`
- **Dry-run:** `True`
- **Agents emitted:** 10

## Per-agent summary

| Agent | Authority | Recommendation | Risk | Confidence | Veto |
|---|---|---|---|---|---|
| `ALLOCATOR_PLAN_CRITIC` | `L0_ADVISORY_ONLY` | `ALLOW` | `LOW` | `LOW` | `False` |
| `DAILY_BRIEF` | `L0_ADVISORY_ONLY` | `ALLOW` | `LOW` | `LOW` | `False` |
| `EQUITY_RECONCILIATION_CRITIC` | `L0_ADVISORY_ONLY` | `ALLOW` | `LOW` | `LOW` | `False` |
| `FINAL_ARBITER` | `L0_ADVISORY_ONLY` | `ALLOW` | `LOW` | `LOW` | `False` |
| `INCIDENT_REVIEW` | `L0_ADVISORY_ONLY` | `ALLOW` | `LOW` | `LOW` | `False` |
| `NO_SIGNAL_DIAGNOSTIC` | `L0_ADVISORY_ONLY` | `ALLOW` | `LOW` | `LOW` | `False` |
| `RISK_REVIEW` | `L0_ADVISORY_ONLY` | `ALLOW` | `LOW` | `LOW` | `False` |
| `SHADOW_CANDIDATE_REVIEW` | `L0_ADVISORY_ONLY` | `ALLOW` | `LOW` | `LOW` | `False` |
| `STRATEGY_REVIEW` | `L0_ADVISORY_ONLY` | `ALLOW` | `LOW` | `LOW` | `False` |
| `TRIGGER_WATCHLIST_REVIEW` | `L0_ADVISORY_ONLY` | `ALLOW` | `LOW` | `LOW` | `False` |

## Standing markers
- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE`
- `NO_LLM_STATE_MUTATION`
- `DETERMINISTIC_GATES_REMAIN_FINAL`
- `LLM_PRE_ORDER_VETO_REMAINS_DISABLED`
- `SCHEDULE_REMAINS_DISABLED_BY_DEFAULT`

## Hard invariants (verified in tests)
- LLM advisory mesh NEVER imports `alpaca_orders`.
- LLM advisory mesh NEVER calls broker.
- LLM advisory mesh NEVER mutates `runtime_state`, `safe_mode`, `broker_repair_required`, or any broker / live flag.
- LLM advisory mesh writes ONLY to `learning-loop/llm_advisory/` and `journal/autonomy/`.
- Every advisory output is validated against the v3.29 `LLMAdvisoryOutput` schema before persistence.
- Secrets are redacted from every persisted field.
