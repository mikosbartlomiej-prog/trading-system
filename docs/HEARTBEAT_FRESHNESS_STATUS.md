# Heartbeat Freshness Status

- Generated at: `2026-08-22T05:00:13.932102+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 236 | 2026-08-22T04:56:17.845343+00:00 |
| `defense-monitor` | FRESH | 260 | 2026-08-22T04:55:54.335133+00:00 |
| `twitter-monitor` | FRESH | 233 | 2026-08-22T04:56:20.938190+00:00 |
| `reddit-monitor` | FRESH | 23898 | 2026-08-21T22:21:56.369256+00:00 |
| `geo-monitor` | FRESH | 1053 | 2026-08-22T04:42:41.129564+00:00 |
| `politician-monitor` | FRESH | 1538 | 2026-08-22T04:34:35.445087+00:00 |
| `options-monitor` | FRESH | 28849 | 2026-08-21T20:59:25.315235+00:00 |
| `options-exit-monitor` | FRESH | 267 | 2026-08-22T04:55:47.062972+00:00 |
| `price-monitor` | FRESH | 28662 | 2026-08-21T21:02:32.174882+00:00 |
| `exit-monitor` | FRESH | 263 | 2026-08-22T04:55:50.500094+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

