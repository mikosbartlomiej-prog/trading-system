# Safe-mode consistency status — 2026-06-17T09:18:45.341254+00:00

## Verdict: **INCONSISTENT_EXIT_WITHOUT_ENTER**

**Blocker:** _none_

## Detail

SAFE_MODE_EXITED at 2026-06-16T16:06:49.182418+00:00 without a matching prior SAFE_MODE_ENTERED in the lookback window

## Counts

- audit events in last 24h: 1
- SAFE_MODE_ENTERED: 0
- SAFE_MODE_EXITED:  1
- runtime_active:    False
- runtime_trigger:   
- last_event_iso:    2026-06-16T16:06:49.182418+00:00

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT`
