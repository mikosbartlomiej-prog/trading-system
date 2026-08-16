# Heartbeat Freshness Status

- Generated at: `2026-08-16T05:01:20.737738+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 321 | 2026-08-16T04:55:59.425359+00:00 |
| `defense-monitor` | FRESH | 408 | 2026-08-16T04:54:32.427064+00:00 |
| `twitter-monitor` | FRESH | 300 | 2026-08-16T04:56:20.352411+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 586 | 2026-08-16T04:51:34.482219+00:00 |
| `politician-monitor` | FRESH | 1427 | 2026-08-16T04:37:34.150705+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 324 | 2026-08-16T04:55:56.978882+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 96 | 2026-08-16T04:59:44.765711+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

