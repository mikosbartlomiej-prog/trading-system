# Heartbeat Freshness Status

- Generated at: `2026-09-20T09:24:51.827776+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 253 | 2026-09-20T09:20:38.898244+00:00 |
| `defense-monitor` | FRESH | 256 | 2026-09-20T09:20:36.111722+00:00 |
| `twitter-monitor` | FRESH | 240 | 2026-09-20T09:20:51.384841+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 1446 | 2026-09-20T09:00:45.493872+00:00 |
| `politician-monitor` | FRESH | 6795 | 2026-09-20T07:31:37.055204+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 261 | 2026-09-20T09:20:30.485522+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 263 | 2026-09-20T09:20:29.318953+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

