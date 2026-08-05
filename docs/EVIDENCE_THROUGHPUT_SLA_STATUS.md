# Evidence Throughput SLA Status

- Generated at: `2026-08-05T07:14:52.770379+00:00`
- Verdict: **FINDING_P0** (exit_code=3)
- Consecutive zero cycles: `128`
- History entries scanned: `128`
- evidence_counters_latest total: `0`

## Latest cycle

- appended_at: `2026-08-04T20:10:43.404375+00:00`
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

