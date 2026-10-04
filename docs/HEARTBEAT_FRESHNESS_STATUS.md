# Heartbeat Freshness Status

- Generated at: `2026-10-04T10:42:55.856664+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 98 | 2026-10-04T10:41:18.149775+00:00 |
| `defense-monitor` | FRESH | 96 | 2026-10-04T10:41:19.946364+00:00 |
| `twitter-monitor` | FRESH | 88 | 2026-10-04T10:41:28.036838+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 3396 | 2026-10-04T09:46:20.068822+00:00 |
| `politician-monitor` | FRESH | 9629 | 2026-10-04T08:02:26.629960+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 404 | 2026-10-04T10:36:11.425016+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 93 | 2026-10-04T10:41:22.457796+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

