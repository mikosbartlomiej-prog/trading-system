# Heartbeat Freshness Status

- Generated at: `2026-07-18T06:27:56.263878+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 140 | 2026-07-18T06:25:36.272345+00:00 |
| `defense-monitor` | FRESH | 131 | 2026-07-18T06:25:44.953004+00:00 |
| `twitter-monitor` | FRESH | 123 | 2026-07-18T06:25:53.174482+00:00 |
| `reddit-monitor` | FRESH | 27626 | 2026-07-17T22:47:29.938890+00:00 |
| `geo-monitor` | FRESH | 2536 | 2026-07-18T05:45:40.736160+00:00 |
| `politician-monitor` | FRESH | 1245 | 2026-07-18T06:07:10.944288+00:00 |
| `options-monitor` | FRESH | 32476 | 2026-07-17T21:26:40.371732+00:00 |
| `options-exit-monitor` | FRESH | 138 | 2026-07-18T06:25:37.884739+00:00 |
| `price-monitor` | FRESH | 32328 | 2026-07-17T21:29:07.948129+00:00 |
| `exit-monitor` | FRESH | 140 | 2026-07-18T06:25:36.352603+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

