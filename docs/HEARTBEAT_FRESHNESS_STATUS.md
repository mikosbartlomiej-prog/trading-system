# Heartbeat Freshness Status

- Generated at: `2026-10-18T09:00:32.240367+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 284 | 2026-10-18T08:55:48.669888+00:00 |
| `defense-monitor` | FRESH | 582 | 2026-10-18T08:50:50.157001+00:00 |
| `twitter-monitor` | FRESH | 270 | 2026-10-18T08:56:02.309282+00:00 |
| `reddit-monitor` | FRESH | 33360 | 2026-10-17T23:44:32.059600+00:00 |
| `geo-monitor` | FRESH | 1780 | 2026-10-18T08:30:51.832526+00:00 |
| `politician-monitor` | FRESH | 1189 | 2026-10-18T08:40:43.204962+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 277 | 2026-10-18T08:55:54.989386+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 285 | 2026-10-18T08:55:47.421975+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

