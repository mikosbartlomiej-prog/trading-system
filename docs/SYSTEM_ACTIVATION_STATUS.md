# SYSTEM ACTIVATION STATUS

_Generated at:_ `2026-07-11T07:19:49.799348+00:00`

## Top-level flags

| Flag | Value |
|---|---|
| `WHOLE_SAFE_STACK_ON` | `True` |
| `WHOLE_SOLUTION_SAFE_ON` | `True` |
| `TRADING_EXECUTION_ON` | `False` |
| `LLM_EXECUTION_AUTHORITY` | `False` |
| `LLM_ADVISORY_ON` | `True` |
| `LLM_PROVIDER_MODE` | `UNAVAILABLE` |
| `ALLOCATOR_ALLOWED` | `True` |
| `SHADOW_ONLY_ALLOWED` | `True` |
| `BROKER_REPAIR_GUARD_WIRED_IN_SAFE_CLOSE` | `True` |
| `RETRY_STORM_SUPPRESSION_ACTIVE` | `True` |
| `SAFE_MODE_CONSISTENCY_CHECK_ACTIVE` | `True` |
| `OPERATOR_ACTION_REQUIRED` | `False` |
| `CODE_WORK_REMAINING` | `False` |
| `OPERATOR_WORK_REMAINING` | `False` |
| `SECRET_WORK_REMAINING` | `True` |
| `MARKET_DATA_WORK_REMAINING` | `True` |

**Master gate decision:** `ALLOCATOR_ALLOWED`  
**LLM advisory status:** `unavailable`

## Subsystems

| Subsystem | Desired | Actual | Enabled? | Blockers | Safety notes |
|---|---|---|---|---|---|
| Broker repair gate | `ENFORCED` | `ENFORCED_CLEAR` | yes | — | deterministic gate, never auto-clears |
| Safe mode | `AUTO` | `INACTIVE` | yes | — | auto on incident triggers; never auto-cleared |
| Safe mode consistency checker | `ENFORCED` | `CONSISTENT` | yes | — | blocks allocator on audit-vs-runtime mismatch |
| Equity reconciliation | `FRESH` | `EQUITY_GAP_OK` | yes | — | blocks allocator if unresolved, schema-invalid, or stale |
| Allocator gate | `ENFORCED` | `ALLOCATOR_ALLOWED` | yes | — | fail-closed default UNKNOWN_BLOCK_FAIL_CLOSED |
| Position reconciliation | `FRESH` | `FRESH_AGE_S=2121700` | yes | — | informational outside market hours |
| Kill switch | `DISARMED` | `DISARMED` | yes | — | informational |
| Discovery reporters | `READ_ONLY_ON` | `MISSING` | no | — | never places orders |
| Trigger watchlist | `READ_ONLY_ON` | `READ_ONLY_ON` | yes | — | never places orders |
| Shadow candidate queue | `READ_ONLY_ON` | `READ_ONLY_ON` | yes | — | shadow only; never places orders |
| Shadow simulator | `READ_ONLY_ON` | `MISSING` | no | — | shadow only; never places orders |
| Outcome tracker | `READ_ONLY_ON` | `MISSING` | no | — | read-only |
| LLM advisory mesh | `ADVISORY_ONLY` | `ADVISORY_UNAVAILABLE` | no | — | LLM has zero execution authority (HARD invariant) |
| Daily operational brief | `DAILY` | `DAILY` | yes | — | read-only documentation |
| Geo monitor | `READ_ONLY_ON` | `READ_ONLY_ON` | yes | — | never places orders unless allocator allows AND broker enabled |
| Crypto monitor | `READ_ONLY_ON` | `READ_ONLY_ON` | yes | — | never places orders unless allocator allows AND broker enabled |
| Price monitor | `READ_ONLY_ON` | `READ_ONLY_ON` | yes | — | never places orders unless allocator allows AND broker enabled |
| Options monitor | `READ_ONLY_ON` | `READ_ONLY_ON` | yes | — | never places orders unless allocator allows AND broker enabled |
| Daily reporters | `DAILY` | `DAILY` | yes | — | read-only |
| Operator dashboard | `READ_ONLY_ON` | `READ_ONLY_ON` | yes | — | read-only |

## Remaining Actions (v3.31)

| Action | Owner | Blocking? | Script / Link | Current status |
|---|---|---|---|---|
| Operator verify Alpaca dashboard for AVAX/USD | `OPERATOR` | no | `docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md` | `resolved` |
| Operator verify Alpaca dashboard for ETH/USD | `OPERATOR` | no | `docs/operator_repair_templates/ETH_USD_repair_marker_template.md` | `resolved` |
| Operator verify Alpaca dashboard for LTC/USD | `OPERATOR` | no | `docs/operator_repair_templates/LTC_USD_repair_marker_template.md` | `resolved` |
| Operator record repair markers | `OPERATOR` | no | `scripts/record_operator_repair_confirmation.py` | `resolved` |
| Operator run clearance proposal | `OPERATOR` | no | `scripts/run_operator_clearance_readiness.py` | `resolved` |
| Operator reconcile safe_mode | `OPERATOR` | no | `scripts/propose_safe_mode_reconciliation.py` | `resolved` |
| GitHub secret GEMINI_API_KEY | `GITHUB_SECRET` | no | `Settings -> Secrets and variables -> Actions` | `pending` |
| Market trigger required for positive entry rows | `MARKET_TRIGGER` | no | `discovery layer` | `observing` |
| Shadow-only requires deterministic gate clean | `SYSTEM (auto when operator clears)` | no | `system_activation_gate` | `resolved` |

---

### Standing markers
- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT`

> This dashboard is read-only. It never calls the broker, never
> places orders, never flips any flag, and never auto-clears safe_mode.
> `TRADING_EXECUTION_ON` and `LLM_EXECUTION_AUTHORITY` are write-time
> literal `False` in `scripts/build_system_activation_status.py`.
