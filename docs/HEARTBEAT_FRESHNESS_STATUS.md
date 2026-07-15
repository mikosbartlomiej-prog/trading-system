# Heartbeat Freshness Status

- Generated at: `2026-07-15T06:35:44.092843+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=9, STALE=0, MISSING=2, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 306 | 2026-07-15T06:30:38.479546+00:00 |
| `defense-monitor` | FRESH | 605 | 2026-07-15T06:25:39.469508+00:00 |
| `twitter-monitor` | FRESH | 277 | 2026-07-15T06:31:06.993910+00:00 |
| `reddit-monitor` | FRESH | 27615 | 2026-07-14T22:55:28.599149+00:00 |
| `geo-monitor` | FRESH | 305 | 2026-07-15T06:30:39.404394+00:00 |
| `politician-monitor` | FRESH | 1119 | 2026-07-15T06:17:04.931032+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 611 | 2026-07-15T06:25:33.508636+00:00 |
| `price-monitor` | FRESH | 34074 | 2026-07-14T21:07:50.165573+00:00 |
| `exit-monitor` | FRESH | 311 | 2026-07-15T06:30:33.214930+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

