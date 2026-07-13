# Heartbeat Freshness Status

- Generated at: `2026-07-13T07:48:19.224699+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 139 | 2026-07-13T07:45:59.953829+00:00 |
| `defense-monitor` | FRESH | 744 | 2026-07-13T07:35:55.622006+00:00 |
| `twitter-monitor` | FRESH | 113 | 2026-07-13T07:46:25.930408+00:00 |
| `reddit-monitor` | FRESH | 32599 | 2026-07-12T22:44:59.992465+00:00 |
| `geo-monitor` | FRESH | 144 | 2026-07-13T07:45:55.394196+00:00 |
| `politician-monitor` | FRESH | 3176 | 2026-07-13T06:55:22.936526+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 133 | 2026-07-13T07:46:05.901354+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 142 | 2026-07-13T07:45:57.352247+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

