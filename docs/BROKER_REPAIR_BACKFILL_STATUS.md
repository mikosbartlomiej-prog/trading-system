# Broker repair backfill status

_Generated at 2026-07-09T08:01:57.403863+00:00 by `scripts/backfill_broker_repair_from_incidents.py`._

## Summary

- Total decisions: 11
- `MARKED`: 3
- `SKIPPED_INSUFFICIENT`: 3
- `SKIPPED_OPERATOR_MARKER`: 5

## Per-symbol/day decisions

| Symbol | Day | Action | FailedCloses | SafeModeEntered | SafeModeExited | Reason |
|--------|-----|--------|--------------|-----------------|----------------|--------|
| AVAX | 2026-06-15 | `SKIPPED_OPERATOR_MARKER` | 104 | 0 | 0 | operator marker exists |
| AVAX/USD | 2026-06-16 | `SKIPPED_OPERATOR_MARKER` | 0 | 0 | 1 | operator marker exists |
| AVAXUSD | 2026-06-15 | `MARKED` | 208 | 0 | 0 | failed_close_count=208 >= 3 AND no SAFE_MODE_EXITED on day |
| DELETE | 2026-06-16 | `SKIPPED_INSUFFICIENT` | 0 | 21 | 0 | failed_close_count=0 < 3 or SAFE_MODE_EXITED_count=0 > 0 |
| ETH | 2026-06-09 | `SKIPPED_OPERATOR_MARKER` | 116 | 0 | 0 | operator marker exists |
| ETH/USD | 2026-06-16 | `SKIPPED_OPERATOR_MARKER` | 0 | 0 | 1 | operator marker exists |
| ETHUSD | 2026-06-09 | `MARKED` | 232 | 0 | 0 | failed_close_count=232 >= 3 AND no SAFE_MODE_EXITED on day |
| GLD | 2026-06-09 | `SKIPPED_INSUFFICIENT` | 1 | 0 | 0 | failed_close_count=1 < 3 or SAFE_MODE_EXITED_count=0 > 0 |
| LTC/USD | 2026-06-16 | `SKIPPED_OPERATOR_MARKER` | 0 | 0 | 1 | operator marker exists |
| LTCUSD | 2026-06-15 | `MARKED` | 208 | 0 | 0 | failed_close_count=208 >= 3 AND no SAFE_MODE_EXITED on day |
| SOLUSD | 2026-06-14 | `SKIPPED_INSUFFICIENT` | 2 | 0 | 0 | failed_close_count=2 < 3 or SAFE_MODE_EXITED_count=0 > 0 |

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
