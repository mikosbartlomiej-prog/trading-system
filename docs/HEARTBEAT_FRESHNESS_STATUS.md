# Heartbeat Freshness Status

- Generated at: `2026-07-24T07:07:22.083814+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 48 | 2026-07-24T07:06:34.010779+00:00 |
| `defense-monitor` | FRESH | 55 | 2026-07-24T07:06:27.237116+00:00 |
| `twitter-monitor` | FRESH | 45 | 2026-07-24T07:06:37.549370+00:00 |
| `reddit-monitor` | FRESH | 29601 | 2026-07-23T22:54:00.909657+00:00 |
| `geo-monitor` | FRESH | 360 | 2026-07-24T07:01:22.309087+00:00 |
| `politician-monitor` | FRESH | 2382 | 2026-07-24T06:27:39.654053+00:00 |
| `options-monitor` | FRESH | 33881 | 2026-07-23T21:42:41.295992+00:00 |
| `options-exit-monitor` | FRESH | 76 | 2026-07-24T07:06:06.435388+00:00 |
| `price-monitor` | FRESH | 33736 | 2026-07-23T21:45:06.327419+00:00 |
| `exit-monitor` | FRESH | 71 | 2026-07-24T07:06:11.002590+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

