# Heartbeat Freshness Status

- Generated at: `2026-08-05T07:14:52.663746+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 246 | 2026-08-05T07:10:46.952415+00:00 |
| `defense-monitor` | FRESH | 248 | 2026-08-05T07:10:44.490802+00:00 |
| `twitter-monitor` | FRESH | 212 | 2026-08-05T07:11:20.345944+00:00 |
| `reddit-monitor` | FRESH | 35870 | 2026-08-04T21:17:02.993824+00:00 |
| `geo-monitor` | FRESH | 2640 | 2026-08-05T06:30:52.301233+00:00 |
| `politician-monitor` | FRESH | 2665 | 2026-08-05T06:30:27.519341+00:00 |
| `options-monitor` | FRESH | 34524 | 2026-08-04T21:39:28.591207+00:00 |
| `options-exit-monitor` | FRESH | 256 | 2026-08-05T07:10:37.153656+00:00 |
| `price-monitor` | FRESH | 34245 | 2026-08-04T21:44:07.512167+00:00 |
| `exit-monitor` | FRESH | 242 | 2026-08-05T07:10:50.828930+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

