# Heartbeat Freshness Status

- Generated at: `2026-06-21T08:45:58.646860+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 33 | 2026-06-21T08:45:25.309858+00:00 |
| `defense-monitor` | FRESH | 25 | 2026-06-21T08:45:33.894596+00:00 |
| `twitter-monitor` | FRESH | 20 | 2026-06-21T08:45:38.538617+00:00 |
| `reddit-monitor` | FRESH | 34764 | 2026-06-20T23:06:34.568676+00:00 |
| `geo-monitor` | FRESH | 13087 | 2026-06-21T05:07:51.947383+00:00 |
| `politician-monitor` | FRESH | 4514 | 2026-06-21T07:30:44.174964+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 34 | 2026-06-21T08:45:24.744172+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 336 | 2026-06-21T08:40:23.130025+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

