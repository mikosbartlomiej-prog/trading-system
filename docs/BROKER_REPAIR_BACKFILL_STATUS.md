# Broker repair backfill status

_Generated at 2026-06-16T09:02:03.211890+00:00 by `scripts/backfill_broker_repair_from_incidents.py`._

## Summary

- Total decisions: 21
- `SKIPPED_ALREADY_MARKED`: 5
- `SKIPPED_INSUFFICIENT`: 16

## Per-symbol/day decisions

| Symbol | Day | Action | FailedCloses | SafeModeEntered | SafeModeExited | Reason |
|--------|-----|--------|--------------|-----------------|----------------|--------|
| AMD | 2026-06-05 | `SKIPPED_INSUFFICIENT` | 1 | 0 | 0 | failed_close_count=1 < 3 or SAFE_MODE_EXITED_count=0 > 0 |
| AVAX | 2026-06-15 | `SKIPPED_ALREADY_MARKED` | 104 | 0 | 0 | symbol already in broker_repair_required state |
| AVAXUSD | 2026-06-15 | `SKIPPED_ALREADY_MARKED` | 208 | 0 | 0 | symbol already in broker_repair_required state |
| CRWD | 2026-06-03 | `SKIPPED_INSUFFICIENT` | 1 | 0 | 0 | failed_close_count=1 < 3 or SAFE_MODE_EXITED_count=0 > 0 |
| CVX | 2026-05-29 | `SKIPPED_INSUFFICIENT` | 1 | 0 | 0 | failed_close_count=1 < 3 or SAFE_MODE_EXITED_count=0 > 0 |
| DELETE | 2026-06-16 | `SKIPPED_INSUFFICIENT` | 0 | 21 | 0 | failed_close_count=0 < 3 or SAFE_MODE_EXITED_count=0 > 0 |
| ETH | 2026-06-08 | `SKIPPED_ALREADY_MARKED` | 152 | 0 | 0 | symbol already in broker_repair_required state |
| ETHUSD | 2026-06-08 | `SKIPPED_ALREADY_MARKED` | 304 | 0 | 0 | symbol already in broker_repair_required state |
| GLD | 2026-06-09 | `SKIPPED_INSUFFICIENT` | 1 | 0 | 0 | failed_close_count=1 < 3 or SAFE_MODE_EXITED_count=0 > 0 |
| LMT | 2026-05-28 | `SKIPPED_INSUFFICIENT` | 1 | 0 | 0 | failed_close_count=1 < 3 or SAFE_MODE_EXITED_count=0 > 0 |
| LTCUSD | 2026-06-15 | `SKIPPED_ALREADY_MARKED` | 208 | 0 | 0 | symbol already in broker_repair_required state |
| NOW | 2026-06-03 | `SKIPPED_INSUFFICIENT` | 1 | 0 | 0 | failed_close_count=1 < 3 or SAFE_MODE_EXITED_count=0 > 0 |
| ORCL | 2026-06-03 | `SKIPPED_INSUFFICIENT` | 1 | 0 | 0 | failed_close_count=1 < 3 or SAFE_MODE_EXITED_count=0 > 0 |
| PANW | 2026-05-29 | `SKIPPED_INSUFFICIENT` | 2 | 0 | 0 | failed_close_count=2 < 3 or SAFE_MODE_EXITED_count=0 > 0 |
| QQQ | 2026-05-28 | `SKIPPED_INSUFFICIENT` | 1 | 0 | 0 | failed_close_count=1 < 3 or SAFE_MODE_EXITED_count=0 > 0 |
| RTX | 2026-05-28 | `SKIPPED_INSUFFICIENT` | 1 | 0 | 0 | failed_close_count=1 < 3 or SAFE_MODE_EXITED_count=0 > 0 |
| SMH | 2026-05-28 | `SKIPPED_INSUFFICIENT` | 1 | 0 | 0 | failed_close_count=1 < 3 or SAFE_MODE_EXITED_count=0 > 0 |
| SOLUSD | 2026-06-14 | `SKIPPED_INSUFFICIENT` | 2 | 0 | 0 | failed_close_count=2 < 3 or SAFE_MODE_EXITED_count=0 > 0 |
| SPY | 2026-05-28 | `SKIPPED_INSUFFICIENT` | 1 | 0 | 0 | failed_close_count=1 < 3 or SAFE_MODE_EXITED_count=0 > 0 |
| TSLA | 2026-05-29 | `SKIPPED_INSUFFICIENT` | 1 | 0 | 0 | failed_close_count=1 < 3 or SAFE_MODE_EXITED_count=0 > 0 |
| XOM | 2026-05-29 | `SKIPPED_INSUFFICIENT` | 1 | 0 | 0 | failed_close_count=1 < 3 or SAFE_MODE_EXITED_count=0 > 0 |

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
