# Heartbeat Freshness Status

- Generated at: `2026-08-07T05:56:13.027818+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 45 | 2026-08-07T05:55:27.953678+00:00 |
| `defense-monitor` | FRESH | 339 | 2026-08-07T05:50:34.057382+00:00 |
| `twitter-monitor` | FRESH | 322 | 2026-08-07T05:50:51.084612+00:00 |
| `reddit-monitor` | FRESH | 16004 | 2026-08-07T01:29:29.281792+00:00 |
| `geo-monitor` | FRESH | 637 | 2026-08-07T05:45:35.599707+00:00 |
| `politician-monitor` | FRESH | 5315 | 2026-08-07T04:27:37.897068+00:00 |
| `options-monitor` | FRESH | 19641 | 2026-08-07T00:28:51.615178+00:00 |
| `options-exit-monitor` | FRESH | 342 | 2026-08-07T05:50:31.120739+00:00 |
| `price-monitor` | FRESH | 19610 | 2026-08-07T00:29:22.798091+00:00 |
| `exit-monitor` | FRESH | 939 | 2026-08-07T05:40:34.267219+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

