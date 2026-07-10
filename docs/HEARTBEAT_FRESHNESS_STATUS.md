# Heartbeat Freshness Status

- Generated at: `2026-07-10T07:58:49.691015+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 187 | 2026-07-10T07:55:42.616247+00:00 |
| `defense-monitor` | FRESH | 185 | 2026-07-10T07:55:44.750159+00:00 |
| `twitter-monitor` | FRESH | 175 | 2026-07-10T07:55:55.069986+00:00 |
| `reddit-monitor` | FRESH | 31758 | 2026-07-09T23:09:31.299969+00:00 |
| `geo-monitor` | FRESH | 788 | 2026-07-10T07:45:41.741886+00:00 |
| `politician-monitor` | FRESH | 1246 | 2026-07-10T07:38:04.021810+00:00 |
| `options-monitor` | FRESH | 39596 | 2026-07-09T20:58:54.121724+00:00 |
| `options-exit-monitor` | FRESH | 194 | 2026-07-10T07:55:36.030782+00:00 |
| `price-monitor` | FRESH | 38137 | 2026-07-09T21:23:12.976446+00:00 |
| `exit-monitor` | FRESH | 191 | 2026-07-10T07:55:38.794433+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

