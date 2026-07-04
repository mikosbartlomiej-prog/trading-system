# Heartbeat Freshness Status

- Generated at: `2026-07-04T07:22:15.971616+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 94 | 2026-07-04T07:20:41.862336+00:00 |
| `defense-monitor` | FRESH | 96 | 2026-07-04T07:20:40.385727+00:00 |
| `twitter-monitor` | FRESH | 84 | 2026-07-04T07:20:51.708469+00:00 |
| `reddit-monitor` | FRESH | 30048 | 2026-07-03T23:01:27.851599+00:00 |
| `geo-monitor` | FRESH | 401 | 2026-07-04T07:15:35.212789+00:00 |
| `politician-monitor` | FRESH | 2023 | 2026-07-04T06:48:33.186256+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 102 | 2026-07-04T07:20:33.621851+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 99 | 2026-07-04T07:20:36.793310+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

