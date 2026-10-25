# Heartbeat Freshness Status

- Generated at: `2026-10-25T09:18:20.530800+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `2`

- Summary: FRESH=8, STALE=2, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 150 | 2026-10-25T09:15:50.347977+00:00 |
| `defense-monitor` | FRESH | 448 | 2026-10-25T09:10:52.195961+00:00 |
| `twitter-monitor` | FRESH | 431 | 2026-10-25T09:11:09.724215+00:00 |
| `reddit-monitor` | FRESH | 33506 | 2026-10-24T23:59:54.494236+00:00 |
| `geo-monitor` | FRESH | 142 | 2026-10-25T09:15:58.770529+00:00 |
| `politician-monitor` | FRESH | 6920 | 2026-10-25T07:23:00.546272+00:00 |
| `options-monitor` | STALE | 121679 | 2026-10-23T23:30:21.758943+00:00 |
| `options-exit-monitor` | FRESH | 154 | 2026-10-25T09:15:46.275804+00:00 |
| `price-monitor` | STALE | 121603 | 2026-10-23T23:31:37.908938+00:00 |
| `exit-monitor` | FRESH | 149 | 2026-10-25T09:15:51.696167+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

