# Heartbeat Freshness Status

- Generated at: `2026-10-24T09:01:20.805532+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 331 | 2026-10-24T08:55:49.823779+00:00 |
| `defense-monitor` | FRESH | 141 | 2026-10-24T08:58:59.736305+00:00 |
| `twitter-monitor` | FRESH | 313 | 2026-10-24T08:56:07.870953+00:00 |
| `reddit-monitor` | FRESH | 42400 | 2026-10-23T21:14:41.146478+00:00 |
| `geo-monitor` | FRESH | 1832 | 2026-10-24T08:30:48.542100+00:00 |
| `politician-monitor` | FRESH | 1016 | 2026-10-24T08:44:25.265776+00:00 |
| `options-monitor` | FRESH | 34259 | 2026-10-23T23:30:21.758943+00:00 |
| `options-exit-monitor` | FRESH | 325 | 2026-10-24T08:55:56.102334+00:00 |
| `price-monitor` | FRESH | 34183 | 2026-10-23T23:31:37.908938+00:00 |
| `exit-monitor` | FRESH | 335 | 2026-10-24T08:55:45.401458+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

