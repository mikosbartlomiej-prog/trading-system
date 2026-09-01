# Evidence Throughput SLA Status

- Generated at: `2026-09-01T09:32:58.281434+00:00`
- Verdict: **FINDING_P0** (exit_code=3)
- Consecutive zero cycles: `200`
- History entries scanned: `200`
- evidence_counters_latest total: `0`

## Latest cycle

- appended_at: `2026-08-31T23:20:54.347631+00:00`
- signals+opportunities: `0`
- collector_status: `SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA`
- workflow_conclusion: `success`

## Thresholds

- WARN at `1` consecutive empty cycle
- FINDING_P1 at `2` consecutive empty cycles
- FINDING_P0 at `3`+ consecutive empty cycles

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

