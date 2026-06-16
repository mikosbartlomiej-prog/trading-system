# Operator clearance readiness

- Evaluated at: `2026-06-16T13:10:50.175974+00:00`
- Overall verdict: **`NOT_READY_NO_MARKER`**
- Dry-run: `True`
- Apply requested: `False`
- Operator confirmed: `False`
- safe_mode_consistency verdict: `INCONSISTENT_ENTERED_NOT_PERSISTED` (blocker='BLOCK_SAFE_MODE_INCONSISTENT')
- equity_gap_reconciliation: block_allocator=`False` verdict=`EQUITY_GAP_OK`
- system_activation_gate decision: `UNKNOWN`

## Per-symbol readiness

| Symbol | Verdict | Marker | Broker repair | Marker ts | Last failure ts | Fresh P13 | Fresh 403 | Proposal | Refusal |
|--------|---------|--------|---------------|-----------|-----------------|-----------|-----------|----------|---------|
| `AVAX/USD` | `NOT_READY_NO_MARKER` | `False` | `True` | `None` | `2026-06-16T09:01:51.513062+00:00` | 0 | 0 | `None` | no operator marker found for 'AVAX/USD'; run scripts/record_operator_repair_confirmation.py --symbol AVAX/USD --operator-confirmed first |
| `ETH/USD` | `NOT_READY_NO_MARKER` | `False` | `True` | `None` | `2026-06-16T09:01:51.514307+00:00` | 0 | 0 | `None` | no operator marker found for 'ETH/USD'; run scripts/record_operator_repair_confirmation.py --symbol ETH/USD --operator-confirmed first |
| `LTC/USD` | `NOT_READY_NO_MARKER` | `False` | `True` | `None` | `2026-06-16T09:01:51.515041+00:00` | 0 | 0 | `None` | no operator marker found for 'LTC/USD'; run scripts/record_operator_repair_confirmation.py --symbol LTC/USD --operator-confirmed first |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT`
- `NO_AUTO_SAFE_MODE_CLEAR_FROM_THIS_SCRIPT`
- `NO_AUTO_BROKER_REPAIR_CLEAR_FROM_THIS_SCRIPT`
- `TEMPLATE_FILE_DOES_NOT_COUNT_AS_MARKER`

_This wrapper NEVER calls the broker, NEVER imports broker plumbing, NEVER clears safe_mode, NEVER clears broker_repair_required, NEVER flips live flags, NEVER fabricates markers. Templates under `docs/operator_repair_templates/` and `learning-loop/operator_markers/templates/` do NOT count as markers._
