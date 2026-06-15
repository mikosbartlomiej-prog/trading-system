# Shadow outcome status

_Generated_: 2026-06-15T10:03:09Z  
_Window_: last 7 days (UTC)

**Source records** are shadow simulations (no broker order submitted, no paper trade). Outcomes are hypothetical observations only and MUST NOT be tallied as paper-trade edge evidence.

## Counters

- Shadow fills:                 0
- Resolved outcomes:            0
- Pending outcomes (this view): 0
- Target-hit-first count:       0
- Stop-hit-first count:         0
- Target-hit-first rate:        None
- Stop-hit-first rate:          None
- Average hypothetical PnL:     None

## Interpretation

**No shadow fills yet.** This is the expected state on a fresh repo or before the runner has been wired to `shared.shadow_simulator.emit_shadow_fill`. Phase 2 work should add the wire-in plus a cron-driven outcome resolution step.

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `SHADOW_ONLY`
- `LLM_ADVISORY_ONLY_CONFIRMED`
