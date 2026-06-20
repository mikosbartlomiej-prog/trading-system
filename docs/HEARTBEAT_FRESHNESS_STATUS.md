# Heartbeat Freshness Status

- Generated at: `2026-06-20T08:02:31.810600+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 121 | 2026-06-20T08:00:30.312306+00:00 |
| `defense-monitor` | FRESH | 426 | 2026-06-20T07:55:25.892395+00:00 |
| `twitter-monitor` | FRESH | 112 | 2026-06-20T08:00:40.226007+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 1024 | 2026-06-20T07:45:28.084456+00:00 |
| `politician-monitor` | FRESH | 599 | 2026-06-20T07:52:33.101500+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 126 | 2026-06-20T08:00:25.497341+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 126 | 2026-06-20T08:00:25.591180+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

