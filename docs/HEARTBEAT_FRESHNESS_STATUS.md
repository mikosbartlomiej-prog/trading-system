# Heartbeat Freshness Status

- Generated at: `2026-11-07T11:16:01.031912+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 296 | 2026-11-07T11:11:04.953881+00:00 |
| `defense-monitor` | FRESH | 296 | 2026-11-07T11:11:05.405621+00:00 |
| `twitter-monitor` | FRESH | 278 | 2026-11-07T11:11:23.251307+00:00 |
| `reddit-monitor` | FRESH | 55289 | 2026-11-06T19:54:31.554574+00:00 |
| `geo-monitor` | FRESH | 896 | 2026-11-07T11:01:04.608094+00:00 |
| `politician-monitor` | FRESH | 8044 | 2026-11-07T09:01:56.965590+00:00 |
| `options-monitor` | FRESH | 41129 | 2026-11-06T23:50:32.185217+00:00 |
| `options-exit-monitor` | FRESH | 298 | 2026-11-07T11:11:03.393507+00:00 |
| `price-monitor` | FRESH | 41028 | 2026-11-06T23:52:12.911941+00:00 |
| `exit-monitor` | FRESH | 295 | 2026-11-07T11:11:05.640237+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

