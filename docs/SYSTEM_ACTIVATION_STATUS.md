# SYSTEM ACTIVATION STATUS

_Generated at:_ `2026-06-16T12:15:10.371215+00:00`

## Top-level flags

| Flag | Value |
|---|---|
| `WHOLE_SAFE_STACK_ON` | `True` |
| `WHOLE_SOLUTION_SAFE_ON` | `True` |
| `TRADING_EXECUTION_ON` | `False` |
| `LLM_EXECUTION_AUTHORITY` | `False` |
| `LLM_ADVISORY_ON` | `True` |
| `LLM_PROVIDER_MODE` | `UNAVAILABLE` |
| `ALLOCATOR_ALLOWED` | `False` |
| `SHADOW_ONLY_ALLOWED` | `True` |
| `BROKER_REPAIR_GUARD_WIRED_IN_SAFE_CLOSE` | `True` |
| `RETRY_STORM_SUPPRESSION_ACTIVE` | `True` |
| `SAFE_MODE_CONSISTENCY_CHECK_ACTIVE` | `True` |
| `OPERATOR_ACTION_REQUIRED` | `True` |
| `OPERATOR_ACTION_REASON` | safe_mode_consistency=INCONSISTENT_ENTERED_NOT_PERSISTED |

## Next operator actions

1. Investigate runtime_state vs audit safe_mode mismatch (see docs/RUNBOOK.md scenario 5a); do NOT auto-clear safe_mode.
2. For each broker-repair symbol: review Alpaca dashboard, manually fix orphaned OCO legs / dust positions, then run `python3 scripts/record_operator_repair_confirmation.py --operator-confirmed`. See docs/OPERATOR_REPAIR_CONFIRMATION.md.

**Master gate decision:** `ALLOCATOR_BLOCKED_SAFE_MODE_INCONSISTENT`  
**Active blockers:** `safe_mode_consistency=INCONSISTENT_ENTERED_NOT_PERSISTED`  
**LLM advisory status:** `unavailable`

## Subsystems

| Subsystem | Desired | Actual | Enabled? | Blockers | Safety notes |
|---|---|---|---|---|---|
| Broker repair gate | `ENFORCED` | `ENFORCED_BLOCKING` | yes | AVAX/USD, ETH/USD, LTC/USD | deterministic gate, never auto-clears |
| Safe mode | `AUTO` | `INACTIVE` | yes | — | auto on incident triggers; never auto-cleared |
| Safe mode consistency checker | `ENFORCED` | `INCONSISTENT_ENTERED_NOT_PERSISTED` | yes | INCONSISTENT_ENTERED_NOT_PERSISTED | blocks allocator on audit-vs-runtime mismatch |
| Equity reconciliation | `FRESH` | `EQUITY_GAP_OK` | yes | — | blocks allocator if unresolved, schema-invalid, or stale |
| Allocator gate | `ENFORCED` | `ALLOCATOR_BLOCKED_SAFE_MODE_INCONSISTENT` | yes | safe_mode_consistency=INCONSISTENT_ENTERED_NOT_PERSISTED | fail-closed default UNKNOWN_BLOCK_FAIL_CLOSED |
| Position reconciliation | `FRESH` | `FRESH_AGE_S=584110` | yes | — | informational outside market hours |
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
