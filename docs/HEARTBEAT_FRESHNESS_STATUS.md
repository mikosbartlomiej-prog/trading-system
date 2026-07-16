# Heartbeat Freshness Status

- Generated at: `2026-07-16T06:43:01.765454+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 145 | 2026-07-16T06:40:36.528295+00:00 |
| `defense-monitor` | FRESH | 439 | 2026-07-16T06:35:42.325037+00:00 |
| `twitter-monitor` | FRESH | 130 | 2026-07-16T06:40:51.787895+00:00 |
| `reddit-monitor` | FRESH | 27966 | 2026-07-15T22:56:55.557783+00:00 |
| `geo-monitor` | FRESH | 746 | 2026-07-16T06:30:35.469609+00:00 |
| `politician-monitor` | FRESH | 1327 | 2026-07-16T06:20:55.189430+00:00 |
| `options-monitor` | FRESH | 35160 | 2026-07-15T20:57:02.188212+00:00 |
| `options-exit-monitor` | FRESH | 145 | 2026-07-16T06:40:36.885790+00:00 |
| `price-monitor` | FRESH | 34950 | 2026-07-15T21:00:31.377565+00:00 |
| `exit-monitor` | FRESH | 148 | 2026-07-16T06:40:33.578005+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

