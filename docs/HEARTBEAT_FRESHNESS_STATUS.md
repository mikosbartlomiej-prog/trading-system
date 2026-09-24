# Heartbeat Freshness Status

- Generated at: `2026-09-24T09:26:48.755916+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 71 | 2026-09-24T09:25:37.325415+00:00 |
| `defense-monitor` | FRESH | 665 | 2026-09-24T09:15:43.634973+00:00 |
| `twitter-monitor` | FRESH | 340 | 2026-09-24T09:21:08.563465+00:00 |
| `reddit-monitor` | FRESH | 33168 | 2026-09-24T00:14:00.821766+00:00 |
| `geo-monitor` | FRESH | 3373 | 2026-09-24T08:30:35.328327+00:00 |
| `politician-monitor` | FRESH | 1245 | 2026-09-24T09:06:04.098528+00:00 |
| `options-monitor` | FRESH | 37001 | 2026-09-23T23:10:08.178799+00:00 |
| `options-exit-monitor` | FRESH | 76 | 2026-09-24T09:25:32.658732+00:00 |
| `price-monitor` | FRESH | 36900 | 2026-09-23T23:11:48.265215+00:00 |
| `exit-monitor` | FRESH | 75 | 2026-09-24T09:25:33.439848+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

