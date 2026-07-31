# Heartbeat Freshness Status

- Generated at: `2026-07-31T07:22:08.332011+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 61 | 2026-07-31T07:21:07.408416+00:00 |
| `defense-monitor` | FRESH | 65 | 2026-07-31T07:21:03.549620+00:00 |
| `twitter-monitor` | FRESH | 57 | 2026-07-31T07:21:10.960877+00:00 |
| `reddit-monitor` | FRESH | 29869 | 2026-07-30T23:04:19.038433+00:00 |
| `geo-monitor` | FRESH | 1269 | 2026-07-31T07:00:59.565289+00:00 |
| `politician-monitor` | FRESH | 2197 | 2026-07-31T06:45:30.908338+00:00 |
| `options-monitor` | FRESH | 34122 | 2026-07-30T21:53:26.277998+00:00 |
| `options-exit-monitor` | FRESH | 70 | 2026-07-31T07:20:58.012670+00:00 |
| `price-monitor` | FRESH | 33991 | 2026-07-30T21:55:37.707910+00:00 |
| `exit-monitor` | FRESH | 72 | 2026-07-31T07:20:56.363460+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

