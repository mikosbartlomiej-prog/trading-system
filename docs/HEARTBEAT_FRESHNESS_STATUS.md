# Heartbeat Freshness Status

- Generated at: `2026-06-24T07:58:54.050361+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 201 | 2026-06-24T07:55:32.629118+00:00 |
| `defense-monitor` | FRESH | 197 | 2026-06-24T07:55:36.560144+00:00 |
| `twitter-monitor` | FRESH | 193 | 2026-06-24T07:55:40.613773+00:00 |
| `reddit-monitor` | FRESH | 31861 | 2026-06-23T23:07:53.313599+00:00 |
| `geo-monitor` | FRESH | 800 | 2026-06-24T07:45:34.034445+00:00 |
| `politician-monitor` | FRESH | 955 | 2026-06-24T07:42:59.501141+00:00 |
| `options-monitor` | FRESH | 38581 | 2026-06-23T21:15:52.565460+00:00 |
| `options-exit-monitor` | FRESH | 206 | 2026-06-24T07:55:28.357306+00:00 |
| `price-monitor` | FRESH | 38490 | 2026-06-23T21:17:24.035617+00:00 |
| `exit-monitor` | FRESH | 206 | 2026-06-24T07:55:28.510865+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

