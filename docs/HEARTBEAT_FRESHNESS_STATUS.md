# Heartbeat Freshness Status

- Generated at: `2026-07-25T06:38:03.142622+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 112 | 2026-07-25T06:36:10.908147+00:00 |
| `defense-monitor` | FRESH | 109 | 2026-07-25T06:36:14.637143+00:00 |
| `twitter-monitor` | FRESH | 97 | 2026-07-25T06:36:25.956783+00:00 |
| `reddit-monitor` | FRESH | 27533 | 2026-07-24T22:59:10.419579+00:00 |
| `geo-monitor` | FRESH | 774 | 2026-07-25T06:25:08.664233+00:00 |
| `politician-monitor` | FRESH | 1096 | 2026-07-25T06:19:46.771942+00:00 |
| `options-monitor` | FRESH | 31876 | 2026-07-24T21:46:47.171523+00:00 |
| `options-exit-monitor` | FRESH | 114 | 2026-07-25T06:36:09.532071+00:00 |
| `price-monitor` | FRESH | 31667 | 2026-07-24T21:50:16.036323+00:00 |
| `exit-monitor` | FRESH | 67 | 2026-07-25T06:36:56.626199+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

