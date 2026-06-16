# Safe-mode consistency status — 2026-06-16T09:08:09.888149+00:00

## Verdict: **INCONSISTENT_ENTERED_NOT_PERSISTED**

**Blocker:** `BLOCK_SAFE_MODE_INCONSISTENT`

## Detail

46 SAFE_MODE_ENTERED in last 48h (latest at 2026-06-16T07:46:09.325630+00:00) with no later SAFE_MODE_EXITED, but runtime_state.safe_mode is not active — persistence bug or workflow-level commit not happening

## Counts

- audit events in last 48h: 46
- SAFE_MODE_ENTERED: 46
- SAFE_MODE_EXITED:  0
- runtime_active:    False
- runtime_trigger:   
- last_event_iso:    2026-06-16T07:46:09.325630+00:00

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT`
