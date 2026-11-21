# Heartbeat Freshness Status

- Generated at: `2026-11-21T12:55:43.133552+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 274 | 2026-11-21T12:51:09.189646+00:00 |
| `defense-monitor` | FRESH | 267 | 2026-11-21T12:51:16.132214+00:00 |
| `twitter-monitor` | FRESH | 260 | 2026-11-21T12:51:23.093777+00:00 |
| `reddit-monitor` | FRESH | 35815 | 2026-11-21T02:58:48.235348+00:00 |
| `geo-monitor` | FRESH | 2373 | 2026-11-21T12:16:10.414731+00:00 |
| `politician-monitor` | FRESH | 2406 | 2026-11-21T12:15:37.618320+00:00 |
| `options-monitor` | FRESH | 39504 | 2026-11-21T01:57:19.354659+00:00 |
| `options-exit-monitor` | FRESH | 276 | 2026-11-21T12:51:06.750623+00:00 |
| `price-monitor` | FRESH | 57547 | 2026-11-20T20:56:36.521230+00:00 |
| `exit-monitor` | FRESH | 279 | 2026-11-21T12:51:04.347804+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

