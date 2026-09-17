# Heartbeat Freshness Status

- Generated at: `2026-09-17T09:35:37.878682+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 308 | 2026-09-17T09:30:30.090941+00:00 |
| `defense-monitor` | FRESH | 303 | 2026-09-17T09:30:35.227967+00:00 |
| `twitter-monitor` | FRESH | 279 | 2026-09-17T09:30:59.099307+00:00 |
| `reddit-monitor` | FRESH | 34244 | 2026-09-17T00:04:53.529173+00:00 |
| `geo-monitor` | FRESH | 305 | 2026-09-17T09:30:32.712687+00:00 |
| `politician-monitor` | FRESH | 6542 | 2026-09-17T07:46:35.398456+00:00 |
| `options-monitor` | FRESH | 37950 | 2026-09-16T23:03:07.825722+00:00 |
| `options-exit-monitor` | FRESH | 605 | 2026-09-17T09:25:33.132563+00:00 |
| `price-monitor` | FRESH | 37756 | 2026-09-16T23:06:21.847489+00:00 |
| `exit-monitor` | FRESH | 1208 | 2026-09-17T09:15:29.396355+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

