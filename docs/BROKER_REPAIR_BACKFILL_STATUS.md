# Broker repair backfill status

_Generated at 2026-07-23T07:06:25.394849+00:00 by `scripts/backfill_broker_repair_from_incidents.py`._

## Summary

- Total decisions: 0

## Per-symbol/day decisions

| Symbol | Day | Action | FailedCloses | SafeModeEntered | SafeModeExited | Reason |
|--------|-----|--------|--------------|-----------------|----------------|--------|

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
