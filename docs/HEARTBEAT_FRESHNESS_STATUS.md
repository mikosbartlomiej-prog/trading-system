# Heartbeat Freshness Status

- Generated at: `2026-06-29T09:15:37.545919+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 307 | 2026-06-29T09:10:30.757516+00:00 |
| `defense-monitor` | FRESH | 306 | 2026-06-29T09:10:31.062789+00:00 |
| `twitter-monitor` | FRESH | 287 | 2026-06-29T09:10:50.524061+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 905 | 2026-06-29T09:00:33.018931+00:00 |
| `politician-monitor` | FRESH | 7186 | 2026-06-29T07:15:51.425857+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 297 | 2026-06-29T09:10:40.207787+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 305 | 2026-06-29T09:10:32.128445+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

