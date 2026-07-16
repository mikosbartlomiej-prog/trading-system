# Broker repair backfill status

_Generated at 2026-07-16T06:43:40.654417+00:00 by `scripts/backfill_broker_repair_from_incidents.py`._

## Summary

- Total decisions: 7
- `MARKED`: 2
- `SKIPPED_INSUFFICIENT`: 1
- `SKIPPED_OPERATOR_MARKER`: 4

## Per-symbol/day decisions

| Symbol | Day | Action | FailedCloses | SafeModeEntered | SafeModeExited | Reason |
|--------|-----|--------|--------------|-----------------|----------------|--------|
| AVAX | 2026-06-16 | `SKIPPED_OPERATOR_MARKER` | 56 | 0 | 0 | operator marker exists |
| AVAX/USD | 2026-06-16 | `SKIPPED_OPERATOR_MARKER` | 0 | 0 | 1 | operator marker exists |
| AVAXUSD | 2026-06-16 | `MARKED` | 112 | 0 | 0 | failed_close_count=112 >= 3 AND no SAFE_MODE_EXITED on day |
| DELETE | 2026-06-16 | `SKIPPED_INSUFFICIENT` | 0 | 21 | 0 | failed_close_count=0 < 3 or SAFE_MODE_EXITED_count=0 > 0 |
| ETH/USD | 2026-06-16 | `SKIPPED_OPERATOR_MARKER` | 0 | 0 | 1 | operator marker exists |
| LTC/USD | 2026-06-16 | `SKIPPED_OPERATOR_MARKER` | 0 | 0 | 1 | operator marker exists |
| LTCUSD | 2026-06-16 | `MARKED` | 200 | 0 | 0 | failed_close_count=200 >= 3 AND no SAFE_MODE_EXITED on day |

## What this script does NOT do

- It does NOT call the broker.
- It does NOT close positions.
- It does NOT cancel orders.
- It does NOT clear `safe_mode`.
- It does NOT flip any trading flag.

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT`
