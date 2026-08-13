# Heartbeat Freshness Status

- Generated at: `2026-08-13T05:57:23.313118+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 95 | 2026-08-13T05:55:48.437277+00:00 |
| `defense-monitor` | FRESH | 89 | 2026-08-13T05:55:54.185097+00:00 |
| `twitter-monitor` | FRESH | 70 | 2026-08-13T05:56:12.851386+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 2490 | 2026-08-13T05:15:53.757458+00:00 |
| `politician-monitor` | FRESH | 954 | 2026-08-13T05:41:29.074091+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 397 | 2026-08-13T05:50:45.819802+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 94 | 2026-08-13T05:55:49.387680+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

