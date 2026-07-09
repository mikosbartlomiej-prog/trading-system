# Evidence Throughput SLA Status

- Generated at: `2026-07-09T08:01:27.516296+00:00`
- Verdict: **FINDING_P0** (exit_code=3)
- Consecutive zero cycles: `60`
- History entries scanned: `60`
- evidence_counters_latest total: `0`

## Latest cycle

- appended_at: `2026-07-08T20:06:10.966516+00:00`
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

